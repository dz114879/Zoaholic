"""
请求处理入口模块。

修改原因：core.handler.py 原来同时承载普通请求、透传请求和调度处理器，文件体积过大。
修改方式：将普通请求处理移入 core.process_request，将透传请求处理移入 core.passthrough，并在此处重新导出旧名字。
目的：不改变外部调用方式，继续兼容 from core.handler import process_request 等旧导入路径。
"""

# 修改原因：外部代码仍从 core.handler 导入这些请求处理函数。
# 修改方式：在 handler 顶部重新导出拆分后的实现。
# 目的：保持兼容，不要求调用方修改导入路径。
from core.process_request import process_request
from core.passthrough import (
    _filter_passthrough_headers,
    _fetch_passthrough_stream,
    _fetch_passthrough_response,
    _passthrough_error_wrapper,
    process_request_passthrough,
)

import json
import asyncio
from collections import defaultdict
from core.json_utils import json_dumps_text, json_loads
from datetime import datetime, timedelta, timezone
from time import time
from urllib.parse import urlparse
from typing import Dict, Union, Optional, Any, Callable, List, TYPE_CHECKING

import httpx
from fastapi import HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from starlette.responses import Response

from core.log_config import logger
from core.streaming import LoggingStreamingResponse
from core.request import get_payload
from core.response import fetch_response, fetch_response_stream, check_response
from core.stats import update_stats
from core.models import (
    RequestModel,
    ImageGenerationRequest,
    AudioTranscriptionRequest,
    ModerationRequest,
    EmbeddingRequest,
)
from core.utils import get_engine, provider_api_circular_list, truncate_for_logging, is_local_api_key
from core.routing import get_right_order_providers
from core.error_response import openai_error_response
from utils import safe_get, error_handling_wrapper, apply_custom_headers, has_header_case_insensitive

if TYPE_CHECKING:
    from fastapi import FastAPI

# 默认超时时间（10分钟，支持长时间 reasoning 请求）
# 默认超时时间（10分钟，支持长时间 reasoning 请求）
DEFAULT_TIMEOUT = 600

# 调试模式标志
is_debug = False


def set_debug_mode(debug: bool):
    """设置调试模式"""
    global is_debug
    is_debug = debug


async def _resolve_oauth_api_key(app: "FastAPI", api_key: Optional[str], channel_id: Optional[str] = None) -> Optional[str]:
    """把指定渠道下的 OAuth key_id 解析成 access_token，静态 key 原样返回。"""
    # 修改原因：oauth_state.json 已按 provider name 分层，同一个 key_id 可能在多个渠道中存在不同凭据。
    # 修改方式：解析时要求调用方传入当前 provider['provider']，只在对应渠道下查找 key_id。
    # 目的：保持静态 key 向后兼容，同时避免 OAuth access_token 被跨渠道误解析。
    if not api_key or not channel_id or app is None or not hasattr(app, "state") or not hasattr(app.state, "oauth_manager"):
        return api_key
    resolved = await app.state.oauth_manager.resolve(channel_id, api_key)
    if resolved is not None:
        # 修改原因：OAuth resolve 只返回 access_token，但部分 channel adapter 还需要 project_id、email 等非敏感字段。
        # 修改方式：解析成功后从 OAuthManager 读取过滤后的 credential 元数据，写入当前请求上下文。
        # 目的：提供通用元数据透传机制，让各 adapter 自行决定是否读取这些字段。
        try:
            from core.middleware import request_info
            current_info = request_info.get()
            if isinstance(current_info, dict):
                current_info["_oauth_resolved"] = True
                metadata = app.state.oauth_manager.get_credential_metadata(channel_id, api_key)
                if metadata:
                    current_info["_oauth_credential_metadata"] = metadata
        except Exception:
            pass
        return resolved
    return api_key


def _fill_failure_provider_info(
    current_info: Dict[str, Any],
    provider_name: Optional[str],
    request_model_name: str,
) -> None:
    # 修改原因：错误路径过去只记录成功请求中的 provider 和 model，导致 500 日志显示“未知”或“-”。
    # 修改方式：在失败统计写入前统一补齐最后尝试的 provider、缺失的 provider_id 和缺失的 model。
    # 目的：让不重试错误和所有重试耗尽错误都能在日志中定位最后失败渠道与请求模型。
    provider_value = provider_name if provider_name else None
    current_info["provider"] = provider_value
    if not current_info.get("provider_id"):
        current_info["provider_id"] = provider_value
    if not current_info.get("model"):
        current_info["model"] = request_model_name


def _fire_and_forget_channel_stats(update_channel_stats_func: Callable, *args, **kwargs) -> None:
    """异步写入 ChannelStat，不依赖 FastAPI BackgroundTasks。

    背景：
    - BackgroundTasks 会在响应生命周期结束后执行。
    - 对于流式接口/客户端提前断开等场景，BackgroundTasks 有可能不被执行，
      导致 channel_stats 缺失，从而 /v1/stats 的成功率永远是 0 或空。

    这里用 create_task 让统计写入尽量独立于请求/响应生命周期。
    """

    async def _run():
        try:
            await update_channel_stats_func(*args, **kwargs)
        except Exception as e:
            # 避免 "Task exception was never retrieved"
            logger.error(f"Error updating channel stats: {str(e)}")

    try:
        asyncio.create_task(_run())
    except RuntimeError:
        # event loop 未就绪（极少数启动/关闭阶段），忽略即可
        pass


def get_preference_value(provider_timeouts: Dict[str, Any], original_model: str) -> Optional[int]:
    """
    根据模型名获取偏好值（如超时时间）
    
    Args:
        provider_timeouts: 偏好配置字典
        original_model: 原始模型名
        
    Returns:
        偏好值，如果未找到则返回 None
    """
    timeout_value = None
    original_model = original_model.lower()
    if original_model in provider_timeouts:
        timeout_value = provider_timeouts[original_model]
    else:
        # 尝试模糊匹配模型
        for timeout_model in provider_timeouts:
            if timeout_model != "default" and timeout_model.lower() in original_model.lower():
                timeout_value = provider_timeouts[timeout_model]
                break
        else:
            # 如果模糊匹配失败，使用渠道的默认值
            timeout_value = provider_timeouts.get("default", None)
    return timeout_value


def get_preference(
    preference_config: Dict[str, Any],
    channel_id: str,
    original_request_model: tuple,
    default_value: int
) -> int:
    """
    获取偏好配置值（如超时时间、keepalive 间隔）
    
    按照 channel_id -> request_model_name -> original_model -> global default 的顺序查找
    
    Args:
        preference_config: 偏好配置字典
        channel_id: 渠道 ID
        original_request_model: (original_model, request_model_name) 元组
        default_value: 默认值
        
    Returns:
        偏好配置值
    """
    original_model, request_model_name = original_request_model
    provider_timeouts = safe_get(preference_config, channel_id, default=preference_config["global"])
    timeout_value = get_preference_value(provider_timeouts, request_model_name)
    if timeout_value is None:
        timeout_value = get_preference_value(provider_timeouts, original_model)
    if timeout_value is None:
        timeout_value = get_preference_value(preference_config["global"], original_model)
    if timeout_value is None:
        timeout_value = preference_config["global"].get("default", default_value)
    return timeout_value


class ModelRequestHandler:
    """
    模型请求处理器
    
    负责根据配置选择 provider、发送请求、处理错误和重试逻辑。
    """
    
    def __init__(
        self,
        app: "FastAPI",
        request_info_getter: Callable[[], Dict[str, Any]],
        update_channel_stats_func: Callable,
        default_timeout: int = DEFAULT_TIMEOUT
    ):
        """
        初始化处理器
        
        Args:
            app: FastAPI 应用实例
            request_info_getter: 获取当前请求信息的函数
            update_channel_stats_func: 更新渠道统计的函数
            default_timeout: 默认超时时间
        """
        self.app = app
        self.request_info_getter = request_info_getter
        self.update_channel_stats_func = update_channel_stats_func
        self.default_timeout = default_timeout
        self.last_provider_indices = defaultdict(lambda: -1)
        self.locks = defaultdict(asyncio.Lock)

    async def _build_attempt_providers(
        self,
        providers: List[Dict[str, Any]],
        request_model_name: str,
        scheduling_algorithm: str,
        advance_cursor: bool = True,
    ) -> List[Dict[str, Any]]:
        """构造单次请求真正用于尝试的渠道列表。

        保留权重展开后的起点选择，但在一次请求内部去掉重复 provider，
        避免同一渠道因为权重槽位被重复尝试很多次。
        """
        if not providers:
            return []

        async def build_unique_group(provider_slots: List[Dict[str, Any]], cursor_key: str) -> List[Dict[str, Any]]:
            """在一个优先级组内执行原有轮转和去重逻辑。"""
            # 修改原因：虚拟路由的 fallback 组间顺序必须稳定，但同组仍要保留原权重槽位轮转语义。
            # 修改方式：把旧的全列表轮转和去重逻辑抽成组内函数，普通路由仍以整列表作为唯一分组。
            # 目的：不改 handler 重试循环，只确保它收到的尝试列表已经符合链条降级顺序。
            if not provider_slots:
                return []

            provider_names = [provider.get("provider") for provider in provider_slots]
            has_duplicate_slots = len(set(provider_names)) != len(provider_names)
            should_rotate_slots = scheduling_algorithm != "fixed_priority" or has_duplicate_slots

            start_index = 0
            if should_rotate_slots:
                async with self.locks[cursor_key]:
                    if advance_cursor:
                        self.last_provider_indices[cursor_key] = (
                            self.last_provider_indices[cursor_key] + 1
                        ) % len(provider_slots)
                    elif self.last_provider_indices[cursor_key] < 0:
                        self.last_provider_indices[cursor_key] = 0
                    start_index = self.last_provider_indices[cursor_key] % len(provider_slots)

            ordered_slots = provider_slots[start_index:] + provider_slots[:start_index]

            unique_group: List[Dict[str, Any]] = []
            seen_provider_names = set()
            for provider in ordered_slots:
                provider_name = provider.get("provider")
                if provider_name in seen_provider_names:
                    continue
                seen_provider_names.add(provider_name)
                unique_group.append(provider)
            return unique_group

        has_virtual_priorities = any(
            provider.get("_virtual_route_provider") and "_virtual_priority" in provider
            for provider in providers
        )
        if not has_virtual_priorities:
            return await build_unique_group(providers, request_model_name)

        # 修改原因：路由阶段会按 _virtual_priority 生成权重槽位，但旧构造逻辑可能因槽位轮转从 fallback 组开始。
        # 修改方式：构造阶段再次按 _virtual_priority 拆组，只在组内轮转和去重，再按 priority 升序合并。
        # 目的：让后续 while 重试循环自然先尝试完当前 chain 节点，再降级到下一个节点。
        priority_groups: Dict[int, List[Dict[str, Any]]] = {}
        for provider in providers:
            try:
                priority = int(provider.get("_virtual_priority", 0) or 0)
            except (TypeError, ValueError):
                priority = 0
            priority_groups.setdefault(priority, []).append(provider)

        unique_providers: List[Dict[str, Any]] = []
        seen_provider_names = set()
        for priority in sorted(priority_groups.keys()):
            cursor_key = f"{request_model_name}::virtual_priority::{priority}"
            for provider in await build_unique_group(priority_groups[priority], cursor_key):
                provider_name = provider.get("provider")
                if provider_name in seen_provider_names:
                    continue
                seen_provider_names.add(provider_name)
                unique_providers.append(provider)

        return unique_providers

    async def request_model(
        self,
        request_data: Union[RequestModel, ImageGenerationRequest, AudioTranscriptionRequest, ModerationRequest, EmbeddingRequest],
        api_index: int,
        background_tasks: BackgroundTasks,
        endpoint: Optional[str] = None,
        dialect_id: Optional[str] = None,
        original_payload: Optional[Dict[str, Any]] = None,
        original_headers: Optional[Dict[str, str]] = None,
        passthrough_only: bool = False,
        override_providers: Optional[List[Dict[str, Any]]] = None,
        force_api_key: Optional[str] = None,
        override_auto_retry: Optional[bool] = None,
        override_timeout: Optional[int] = None,
    ) -> Response:
        """
        处理模型请求
        
        Args:
            request_data: 请求数据
            api_index: API key 索引
            background_tasks: 后台任务
            endpoint: 请求端点
            dialect_id: 入口方言 ID（原生路由传入）
            original_payload: 原始 native 请求体（透传用）
            original_headers: 原始请求头（透传用）
            override_auto_retry: override provider 测试是否允许按候选列表自动重试
            
        Returns:
            响应对象
        """
        config = self.app.state.config
        request_model_name = request_data.model

        # ── override 模式：跳过用户限速和全局路由（测试/直接调用场景） ──
        if override_providers is not None:
            matching_providers = override_providers
            num_matching_providers = len(matching_providers)
            if num_matching_providers == 0:
                raise HTTPException(status_code=400, detail="No providers specified for test")
            scheduling_algorithm = "fixed_priority"
            # 修改原因：普通单渠道测试应只测当前渠道，但虚拟路由测试需要按 chain 候选继续尝试后续节点。
            # 修改方式：保留默认不重试；只有调用方显式传 override_auto_retry=True 时才开启 override provider 列表内重试。
            # 目的：不改变现有渠道测试语义，同时让虚拟模型测试能覆盖完整 fallback 链条。
            auto_retry = bool(override_auto_retry)
            role = "test"
        else:
            # ── 正常路径：用户限速 + 全局路由 ──
            try:
                final_api_key = self.app.state.api_list[api_index]
                await self.app.state.user_api_keys_rate_limit[final_api_key].next(request_model_name)
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=429, detail="Too many requests")

            if not safe_get(config, 'api_keys', api_index, 'model'):
                raise HTTPException(status_code=404, detail=f"No matching model found: {request_model_name}")

            scheduling_algorithm = safe_get(
                config, 'api_keys', api_index, "preferences", "SCHEDULING_ALGORITHM",
                default=safe_get(config, "preferences", "SCHEDULING_ALGORITHM", default="fixed_priority")
            )

            request_total_tokens = 0
            if request_data and isinstance(request_data, RequestModel):
                for message in request_data.messages:
                    if message.content and isinstance(message.content, str):
                        request_total_tokens += len(message.content)
            request_total_tokens = int(request_total_tokens / 4)

            matching_providers = await get_right_order_providers(
                request_model_name, config, api_index, scheduling_algorithm, 
                self.app, request_total_tokens=request_total_tokens
            )
            matching_providers = await self._build_attempt_providers(
                matching_providers,
                request_model_name=request_model_name,
                scheduling_algorithm=scheduling_algorithm,
                advance_cursor=True,
            )
            num_matching_providers = len(matching_providers)

            auto_retry = safe_get(config, 'api_keys', api_index, "preferences", "AUTO_RETRY", default=True)
            role = safe_get(
                config, 'api_keys', api_index, "role", 
                default=safe_get(config, 'api_keys', api_index, "api", default="None")[:8]
            )

        status_code = 500
        error_message = None

        index = 0
        # 获取配置的最大重试次数上限，默认为 10
        # [已废弃] max_retry_count 机制已移除，重试终止完全靠 is_all_rate_limited 兜底
        # max_retry_limit = safe_get(config, 'preferences', 'max_retry_count', default=0)

        # 计算最大尝试次数（包含首轮 + 自动重试）。
        # 修复：
        # - 使用 get_enabled_items_count 排除禁用 key。
        #   容易在“只有 1 个可用 key，但配置里堆了大量禁用 key”时触发 1000+ 次重试。
        # - 统一按“启用的 key 数量”计算。
        def _provider_key_slots(p: Dict[str, Any]) -> int:
            """返回该 provider 可用于重试的 key 数量（至少为 1）。

            注意：没有配置 api（例如无需 key 的渠道）也按 1 计。
            """
            try:
                enabled = provider_api_circular_list[p["provider"]].get_enabled_items_count()
            except Exception:
                enabled = 0
            try:
                enabled_int = int(enabled)
            except (TypeError, ValueError):
                enabled_int = 0
            return max(1, enabled_int)

        def _calc_retry_count(providers: List[Dict[str, Any]]) -> int:
            """计算“额外重试次数”。

            设计目标：
            - 保持原有语义：总尝试次数 ≈ num_matching_providers + retry_count
            不设人为上限，终止靠 is_all_rate_limited 兜底
            - 仅按“启用的 key 数量”估算，避免禁用 key 造成 retry_count 虚高
            """
            n = len(providers)
            if n <= 0:
                return 0

            if n == 1:
                slots = _provider_key_slots(providers[0])
                # 单 provider：至少允许 1 次重试；若有多 key，可覆盖更多 key
                base = slots if slots > 1 else 1
                return base

            total_slots = sum(_provider_key_slots(p) for p in providers)
            tmp_retry_count = total_slots * 2
            return tmp_retry_count

        retry_count = _calc_retry_count(matching_providers)
        max_attempts = min(num_matching_providers + retry_count, 500)  # 绝对上限防死循环

        # 初始化重试路径记录
        retry_path: List[Dict[str, Any]] = []
        current_retry_count = 0

        # ── 虚拟路由优先级分组索引 ──
        # matching_providers 已按 _virtual_priority 升序排列（0,0,0,1,1,2...）
        # 构建 priority_group_ranges: [(start, end, priority), ...]
        # 用于重试循环中强制在同一 priority group 内走到黑，再降级
        _is_virtual_route = any(
            p.get("_virtual_route_provider") and "_virtual_priority" in p
            for p in matching_providers
        )
        _priority_group_ranges: list = []  # [(start_idx, end_idx_exclusive, priority)]
        if _is_virtual_route:
            _cur_priority = None
            _group_start = 0
            for _i, _p in enumerate(matching_providers):
                _pp = int(_p.get("_virtual_priority", 0) or 0)
                if _cur_priority is not None and _pp != _cur_priority:
                    _priority_group_ranges.append((_group_start, _i, _cur_priority))
                    _group_start = _i
                _cur_priority = _pp
            if _cur_priority is not None:
                _priority_group_ranges.append((_group_start, len(matching_providers), _cur_priority))

        def _get_priority_group_range(idx: int):
            """返回 idx 所在 priority group 的 (start, end) 范围"""
            for start, end, _ in _priority_group_ranges:
                if start <= idx < end:
                    return start, end
            return 0, num_matching_providers

        while True:
            if index >= max_attempts:
                break
            current_index = index % num_matching_providers
            index += 1
            provider = matching_providers[current_index]

            provider_name = provider['provider']

            # 检查是否所有 API 密钥都被速率限制
            model_dict = provider["_model_dict_cache"]
            original_model = model_dict[request_model_name]
            if not override_providers and provider_name in provider_api_circular_list:
                if await provider_api_circular_list[provider_name].is_all_rate_limited(original_model):
                    error_message = "All API keys are rate limited and stop auto retry!"
                    if num_matching_providers == 1:
                        break
                    # 虚拟路由：检查同 priority group 是否全部耗尽
                    if _is_virtual_route:
                        grp_start, grp_end = _get_priority_group_range(current_index)
                        group_all_exhausted = all(
                            await provider_api_circular_list[matching_providers[gi]["provider"]].is_all_rate_limited(original_model)
                            if matching_providers[gi]["provider"] in provider_api_circular_list else True
                            for gi in range(grp_start, grp_end)
                        )
                        if not group_all_exhausted:
                            # 同组还有可用渠道 → 跳到组内下一个，不降级
                            continue
                        # 同组全耗尽 → 跳过整个组，直接到下一个 priority group
                        index = (grp_end % num_matching_providers) if grp_end < num_matching_providers else grp_end
                    continue

            original_request_model = (original_model, request_data.model)
            
            # 处理本地聚合器 Key 代理
            if is_local_api_key(provider_name) and provider_name in self.app.state.api_list:
                local_provider_api_index = self.app.state.api_list.index(provider_name)
                local_provider_scheduling_algorithm = safe_get(
                    config, 'api_keys', local_provider_api_index, "preferences", 
                    "SCHEDULING_ALGORITHM", default="fixed_priority"
                )
                local_provider_matching_providers = await get_right_order_providers(
                    request_model_name, config, local_provider_api_index, 
                    local_provider_scheduling_algorithm, self.app, 
                    request_total_tokens=request_total_tokens
                )
                local_timeout_value = 0
                for local_provider in local_provider_matching_providers:
                    local_provider_name = local_provider['provider']
                    if not is_local_api_key(local_provider_name):
                        local_timeout_value += get_preference(
                            self.app.state.provider_timeouts, local_provider_name, 
                            original_request_model, self.default_timeout
                        )
                local_provider_num_matching_providers = len(local_provider_matching_providers)
            else:
                local_timeout_value = get_preference(
                    self.app.state.provider_timeouts, provider_name, 
                    original_request_model, self.default_timeout
                )
                local_provider_num_matching_providers = 1

            local_timeout_value = local_timeout_value * local_provider_num_matching_providers

            # override_timeout 覆盖渠道默认 timeout（测试场景用）
            if override_timeout is not None and override_timeout > 0:
                local_timeout_value = override_timeout

            keepalive_interval = get_preference(
                self.app.state.keepalive_interval, provider_name, 
                original_request_model, 99999
            )
            if keepalive_interval > local_timeout_value:
                keepalive_interval = None
            if is_local_api_key(provider_name):
                keepalive_interval = None

            try:
                passthrough_ctx = None
                if dialect_id and original_payload is not None and isinstance(request_data, RequestModel):
                    from core.dialects.passthrough import evaluate_passthrough
                    passthrough_ctx = await evaluate_passthrough(
                        dialect_id=dialect_id,
                        original_payload=original_payload,
                        original_headers=original_headers or {},
                        target_provider=provider,
                        request_model=request_model_name,
                    )

                # passthrough_only 前置拦截：如果该端点仅支持透传，
                # 但当前 provider 与入口方言不匹配（透传未启用），
                # 直接跳过该 provider，不发送任何真实上游请求。
                if passthrough_only and not (passthrough_ctx and passthrough_ctx.enabled):
                    error_message = f"Endpoint {endpoint} requires passthrough mode, but provider {provider_name} is not compatible"
                    status_code = 501
                    continue

                process_fn = process_request_passthrough if (passthrough_ctx and passthrough_ctx.enabled) else process_request
                response = await process_fn(
                    request_data, provider, background_tasks, self.app,
                    self.request_info_getter, self.update_channel_stats_func,
                    passthrough_ctx=passthrough_ctx,
                    endpoint=endpoint,
                    role=role,
                    timeout_value=local_timeout_value,
                    keepalive_interval=keepalive_interval,
                ) if process_fn is process_request_passthrough else await process_request(
                    request_data, provider, background_tasks, self.app,
                    self.request_info_getter, self.update_channel_stats_func,
                    endpoint, role, local_timeout_value, keepalive_interval,
                    force_api_key=force_api_key
                )

                # 成功时记录重试路径和重试次数
                current_info = self.request_info_getter()
                if retry_path:
                    current_info["retry_path"] = json.dumps(retry_path, ensure_ascii=False)
                current_info["retry_count"] = current_retry_count
                return response
            except asyncio.CancelledError:
                # 客户端取消请求，直接向上抛出，不再重试
                logger.info(f"Request cancelled by client for model {request_model_name}")
                raise
            except (Exception, HTTPException, httpx.ReadError,
                    httpx.RemoteProtocolError, httpx.LocalProtocolError, httpx.ReadTimeout,
                    httpx.ConnectError) as e:
                # 记录重试路径
                current_retry_count += 1
                
                # 获取完整的错误详情
                error_details = getattr(e, "detail", None) if isinstance(e, HTTPException) else None
                if isinstance(error_details, (dict, list)):
                    try:
                        full_error = json.dumps(error_details, ensure_ascii=False)
                    except Exception:
                        full_error = str(error_details)
                elif isinstance(e, HTTPException):
                    full_error = str(error_details) if error_details is not None else str(e)
                else:
                    full_error = str(e)

                retry_path.append({
                    "provider": provider_name,
                    "error": full_error[:2000],  # 增加错误信息长度限制到 2000 字符
                    "status_code": None  # 稍后更新
                })

                # 根据异常类型设置状态码和错误消息
                if isinstance(e, httpx.ReadTimeout):
                    status_code = 504  # Gateway Timeout
                    timeout_value = e.request.extensions.get('timeout', {}).get('read', -1)
                    error_message = f"Request timed out after {timeout_value} seconds"
                elif isinstance(e, httpx.ConnectError):
                    status_code = 503  # Service Unavailable
                    error_message = "Unable to connect to service"
                elif isinstance(e, httpx.ReadError):
                    status_code = 502  # Bad Gateway
                    error_message = "Network read error"
                elif isinstance(e, httpx.RemoteProtocolError):
                    status_code = 502  # Bad Gateway
                    error_message = "Remote protocol error"
                    
                    # 检测 HTTP/2 StreamReset 错误，自动重置连接池
                    error_str = str(e)
                    if "StreamReset" in error_str or "stream_id" in error_str:
                        try:
                            # 从 provider 的 base_url 提取 host 并重置连接
                            base_url = provider.get('base_url', '')
                            if base_url:
                                host = urlparse(base_url).netloc
                                if host and hasattr(self.app.state, 'client_manager'):
                                    await self.app.state.client_manager.reset_client(host)
                                    logger.info(f"Auto-reset HTTP/2 connection for {host} due to StreamReset error")
                        except Exception as reset_err:
                            logger.warning(f"Failed to auto-reset connection: {reset_err}")
                elif isinstance(e, httpx.LocalProtocolError):
                    status_code = 502  # Bad Gateway
                    error_message = "Local protocol error"
                elif isinstance(e, HTTPException):
                    status_code = e.status_code
                    # 错误解析应尽量由各渠道适配器完成，这里只做通用兜底。
                    error_message = str(getattr(e, "detail", None) or str(e))
                else:
                    status_code = 500  # Internal Server Error
                    error_message = str(e) or f"Unknown error: {e.__class__.__name__}"

                # ── Key Rules 统一错误处理 ──
                from core.key_rules import apply_key_rule_retry_override, resolve_key_rules, match_key_rules
                _key_rules = resolve_key_rules(provider.get("preferences") or {})
                _rule_result = match_key_rules(_key_rules, status_code, error_message) if _key_rules else None

                # 规则中的 remap: 把上游非标准状态码映射为标准码
                if _rule_result and _rule_result.get("remap"):
                    _mapped = _rule_result["remap"]
                    if 100 <= _mapped <= 599:
                        status_code = _mapped

                exclude_error_rate_limit = [
                    "BrokenResourceError",
                    "Proxy connection timed out",
                    "Unknown error: EndOfStream",
                    "'status': 'INVALID_ARGUMENT'",
                    "Unable to connect to service",
                    "Connection closed unexpectedly",
                    "Invalid JSON payload received. Unknown name ",
                    "User location is not supported for the API use",
                    "The model is overloaded. Please try again later.",
                    "[SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] sslv3 alert handshake failure (_ssl.c:1007)",
                    "<title>Worker exceeded resource limits",
                ]

                channel_id = provider['provider']

                # ★ 修复：优先从 request_info 获取本次实际使用的 api_key，
                # 避免并发场景下 after_next_current() 返回其他请求的 key，
                # 导致冷却/禁用操作作用在错误的 key 上。
                _current_info_for_key = self.request_info_getter()
                current_api = _current_info_for_key.get("_used_api_key") or \
                    await provider_api_circular_list[channel_id].after_next_current()

                should_consider_channel_cooldown = (
                    self.app.state.channel_manager.cooldown_period > 0
                    and override_providers is None
                    and num_matching_providers > 1
                    and all(error not in error_message for error in exclude_error_rate_limit)
                )

                # 仅统计"启用"的 key 数量，避免禁用 key 造成误判。
                try:
                    api_key_count_before_rule = provider_api_circular_list[channel_id].get_enabled_items_count()
                except Exception:
                    api_key_count_before_rule = provider_api_circular_list[channel_id].get_items_count()

                key_rule_disabled_current = False
                # ── 应用 Key Rules 规则：冷却 / 禁用 ──
                if _rule_result and current_api:
                    _duration = _rule_result.get("duration", 0)
                    _reason = _rule_result.get("reason", "key_rule")
                    if _duration == -1:
                        # 永久禁用
                        await provider_api_circular_list[channel_id].set_auto_disabled(
                            current_api, duration=0, reason=_reason
                        )
                        key_rule_disabled_current = True
                    elif _duration > 0:
                        # 修改原因：旧逻辑只在多 key 时冷却，单渠道单 key 依赖原有重试行为；但多渠道降级时，最后一个失败 key 必须能让渠道被判定为耗尽。
                        # 修改方式：多 key 仍按旧规则冷却；当渠道级降级条件成立时，最后一个 key 也执行冷却。
                        # 目的：既保留单渠道单 key 的旧行为，又让多渠道虚拟路由能在所有 key 不可用后再进入 fallback。
                        if (
                            (api_key_count_before_rule > 1 or should_consider_channel_cooldown)
                            and all(error not in error_message for error in exclude_error_rate_limit)
                        ):
                            await provider_api_circular_list[channel_id].set_auto_disabled(
                                current_api, duration=_duration, reason=_reason
                            )
                            key_rule_disabled_current = True

                # 仅统计"启用"的 key 数量，避免禁用 key 造成误判。
                # 修改原因：旧逻辑先冷却渠道再冷却 key，会把同渠道剩余 key 从候选列表中埋没。
                # 修改方式：key 级规则执行后，再检查该渠道是否还有启用 key。
                # 目的：只有当前渠道所有 key 都不可用时，才进入渠道级冷却和候选列表重建。
                try:
                    api_key_count = provider_api_circular_list[channel_id].get_enabled_items_count()
                except Exception:
                    api_key_count = provider_api_circular_list[channel_id].get_items_count()

                should_rebuild_after_channel_cooldown = (
                    should_consider_channel_cooldown
                    and (api_key_count <= 0 or not key_rule_disabled_current)
                )

                if should_rebuild_after_channel_cooldown:
                    # 修改原因：只有当前错误确实触发 key 禁用时，才应等待当前渠道所有 key 耗尽；未命中 key_rules 时继续留在当前渠道会反复取到同一 key。
                    # 修改方式：key 已被禁用时沿用“启用 key 数量为 0 才冷却渠道”；key 未被禁用时立即走渠道级冷却并重建候选列表。
                    # 目的：既保留多 key 渠道先耗尽 key 的行为，又避免无匹配 key_rules 的渠道在虚拟路由中循环重试。
                    await self.app.state.channel_manager.exclude_model(channel_id, request_model_name)
                    matching_providers = await get_right_order_providers(
                        request_model_name, config, api_index, scheduling_algorithm,
                        self.app, request_total_tokens=request_total_tokens
                    )
                    matching_providers = await self._build_attempt_providers(
                        matching_providers,
                        request_model_name=request_model_name,
                        scheduling_algorithm=scheduling_algorithm,
                        advance_cursor=False,
                    )
                    last_num_matching_providers = num_matching_providers
                    num_matching_providers = len(matching_providers)
                    # provider 列表发生变化（或重新排序）时，重算最大尝试次数
                    retry_count = _calc_retry_count(matching_providers)
                    max_attempts = min(num_matching_providers + retry_count, 500)  # 绝对上限防死循环
                    if num_matching_providers != last_num_matching_providers:
                        index = 0
                # 当 key 被冷却但渠道仍有可用 key 时：不做 exclude_model，也不回退 index。
                # index 正常前进，通过 max_attempts 的 modulo 循环回来时 circular_list 自动取下一个 key。
                # 不能 index = current_index，否则 index 永远到不了 max_attempts，死循环。

                # 有些错误并没有请求成功，所以需要删除请求记录
                if (current_api 
                    and any(error in error_message for error in exclude_error_rate_limit) 
                    and provider_api_circular_list[provider_name].requests[current_api][original_model]):
                    provider_api_circular_list[provider_name].requests[current_api][original_model].pop()

                # 根据错误消息调整状态码
                if "string_above_max_length" in error_message:
                    status_code = 413
                if "must be less than max_seq_len" in error_message:
                    status_code = 413
                if "Please reduce the length of the messages or completion" in error_message:
                    status_code = 413
                if "Request contains text fields that are too large." in error_message:
                    status_code = 413
                # openrouter
                if "Please reduce the length of either one, or use the" in error_message:
                    status_code = 413
                # gemini
                if "exceeds the maximum number of tokens allowed" in error_message:
                    status_code = 413
                if ("'reason': 'API_KEY_INVALID'" in error_message 
                    or "API key not valid" in error_message 
                    or "API key expired" in error_message):
                    status_code = 401
                if "User location is not supported for the API use." in error_message:
                    status_code = 403
                if "<center><h1>400 Bad Request</h1></center>" in error_message:
                    status_code = 502
                if "The response was filtered due to the prompt triggering Azure OpenAI's content management policy." in error_message:
                    status_code = 403
                if "<head><title>413 Request Entity Too Large</title></head>" in error_message:
                    status_code = 429

                logger.error(f"Error {status_code} with provider {channel_id} API key: {current_api}: {error_message}")
                if is_debug:
                    import traceback
                    traceback.print_exc()

                # 更新重试路径中的状态码
                if retry_path:
                    retry_path[-1]["status_code"] = status_code

                retry_enabled = (
                    auto_retry
                    and (
                        status_code not in [400, 413, 401, 403]
                        or urlparse(provider.get('base_url', '')).netloc == 'models.inference.ai.azure.com'
                    )
                )

                # 修改原因：Key Rules 新增 retry 三态，需要在默认硬编码判断之后提供按规则覆盖的能力。
                # 修改方式：只有 _rule_result.retry 为 bool 时覆盖 retry_enabled，缺失时保持默认结果。
                # 目的：支持 retry=true 强制允许重试、retry=false 强制禁止重试，同时不影响旧配置。
                retry_enabled = apply_key_rule_retry_override(_rule_result, retry_enabled)

                # 测试模式（override + auto_retry=False）：key_rule 的冷却/禁用照常执行，但不重试
                if not auto_retry:
                    retry_enabled = False

                # 特定场景禁止重试：
                # 1. 图像生成失败（no image was generated）通常是内容审核或模型能力问题，重试无效且增加负载
                if "no image was generated" in error_message.lower():
                    retry_enabled = False
                
                # 2. 图像模型遇到 429，通常意味着高并发触发了严格配额，重试会放大负载
                is_image_model = "-image" in request_model_name.lower() or "image-generation" in request_model_name.lower()
                if is_image_model and status_code == 429:
                    retry_enabled = False

                # 若还有剩余尝试次数，则进行自动重试
                if retry_enabled and index < max_attempts:
                    if status_code in {429, 500, 502, 503, 504}:
                        base_delay = 0.5 if status_code == 429 else 0.2
                        # current_retry_count 从 1 开始；最多指数到 2^5，再封顶 5 秒
                        delay = min(5.0, base_delay * (2 ** min(max(current_retry_count - 1, 0), 5)))
                        await asyncio.sleep(delay)
                    # 虚拟路由：重试时强制留在同一 priority group 内
                    if _is_virtual_route and _priority_group_ranges:
                        grp_start, grp_end = _get_priority_group_range(current_index)
                        next_idx = index % num_matching_providers
                        if next_idx >= grp_end or next_idx < grp_start:
                            # 即将越过当前 group → 检查组内是否还有可用 key
                            group_has_available = False
                            for gi in range(grp_start, grp_end):
                                gi_name = matching_providers[gi]["provider"]
                                if gi_name in provider_api_circular_list:
                                    if not await provider_api_circular_list[gi_name].is_all_rate_limited(original_model):
                                        group_has_available = True
                                        break
                            if group_has_available:
                                index = grp_start  # 回到组头继续试
                    continue

                # retry_enabled 但已无重试额度：跳出循环，走统一的“所有重试失败”出口
                if retry_enabled and index >= max_attempts:
                    break

                # 不重试：直接返回本次错误
                # 失败时也记录重试信息和统计
                current_info = self.request_info_getter()
                # 修改原因：不重试错误会直接写入失败统计，过去没有补齐渠道和模型字段。
                # 修改方式：在写 retry_path 和失败状态前调用统一 helper，写入最后尝试 provider 与请求模型。
                # 目的：避免直接返回 500 或其他错误时日志 provider 显示“未知”、model 显示“-”。
                _fill_failure_provider_info(current_info, provider_name, request_model_name)
                if retry_path:
                    current_info["retry_path"] = json.dumps(retry_path, ensure_ascii=False)
                current_info["retry_count"] = current_retry_count
                current_info["success"] = False
                current_info["status_code"] = status_code
                # 记录处理时间
                if "start_time" in current_info:
                    process_time = time() - current_info["start_time"]
                    current_info["process_time"] = process_time
                # 写入失败统计
                background_tasks.add_task(update_stats, current_info, app=self.app)
                return openai_error_response(
                    f"Error: Current provider response failed: {error_message}",
                    status_code,
                )

        # 所有重试都失败
        current_info = self.request_info_getter()
        current_info["first_response_time"] = -1
        current_info["success"] = False
        current_info["status_code"] = status_code
        # 修改原因：所有重试失败时旧逻辑把 provider 写成 None，丢失最后一次尝试的渠道。
        # 修改方式：复用失败字段补全 helper，只在 provider_id 和 model 缺失时补写它们。
        # 目的：让重试耗尽后的日志至少保留最后失败渠道和原始请求模型。
        _fill_failure_provider_info(current_info, provider_name, request_model_name)
        # 记录最终的重试信息
        if retry_path:
            current_info["retry_path"] = json.dumps(retry_path, ensure_ascii=False)
        current_info["retry_count"] = current_retry_count
        # 记录处理时间
        if "start_time" in current_info:
            process_time = time() - current_info["start_time"]
            current_info["process_time"] = process_time
        # 写入失败统计
        background_tasks.add_task(update_stats, current_info, app=self.app)
        return openai_error_response(
            f"All {request_data.model} error: {error_message}",
            status_code,
        )
