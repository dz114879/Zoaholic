from dataclasses import dataclass
from typing import Any, Awaitable, Callable, AsyncIterator, Dict, List, Optional

import httpx


# Type aliases for better readability
# - RequestAdapter: build (url, headers, payload) for a given provider/engine/request
# - StreamAdapter: handle streaming responses
# - ResponseAdapter: handle non-stream responses (仍然是 async generator)
# - ModelsAdapter: fetch models list for a given provider config
RequestAdapter = Callable[
    [Any, str, Dict[str, Any], Optional[str]],
    Awaitable[tuple[str, Dict[str, Any], Dict[str, Any]]],
]

StreamAdapter = Callable[
    [httpx.AsyncClient, str, Dict[str, Any], Dict[str, Any], str, str, int],
    AsyncIterator[Any],
]

ResponseAdapter = Callable[
    [httpx.AsyncClient, str, Dict[str, Any], Dict[str, Any], str, str, int],
    AsyncIterator[Any],
]

# PassthroughStreamAdapter / PassthroughResponseAdapter: 透传模式下的渠道自定义上游响应处理器。
# 修改原因：AWS Bedrock 流式响应是二进制事件流，通用 SSE 透传处理器无法解析。
# 修改方式：在注册表层增加两个可选钩子，让特殊渠道只替换透传响应读取部分。
# 目的：保持普通透传渠道沿用默认处理，同时允许 AWS 将 Bedrock 事件流转换为 Claude SSE。
PassthroughStreamAdapter = Callable[
    [httpx.AsyncClient, str, Dict[str, Any], Dict[str, Any], str, int],
    AsyncIterator[Any],
]

PassthroughResponseAdapter = Callable[
    [httpx.AsyncClient, str, Dict[str, Any], Dict[str, Any], str, int],
    AsyncIterator[Any],
]

# ModelsAdapter: 根据 provider 配置获取模型列表
# 参数: (client, provider_config) -> 返回模型 ID 列表
ModelsAdapter = Callable[
    [httpx.AsyncClient, Dict[str, Any]],
    Awaitable[List[str]],
]

# PassthroughPayloadAdapter: 透传模式下对 native payload 做渠道级修饰（例如 system_prompt 注入）
PassthroughPayloadAdapter = Callable[
    [Dict[str, Any], Dict[str, Any], Any, str, Dict[str, Any], Optional[str]],
    Awaitable[Dict[str, Any]],
]


@dataclass
class ChannelDefinition:
    """
    通用渠道定义:
    - id: 渠道唯一标识(通常对应 engine, 如 "openai" / "gemini" / "vertex-gemini")
    - type_name: 渠道类型名(如 "openai" / "gemini" 等, 用于分类/展示)
    - default_base_url: 默认的 Base URL (可选, 用于前端自动填充)
    - auth_header: 认证头格式 (可选, 如 "Bearer {api_key}" 或 "x-api-key: {api_key}")
    - description: 渠道描述 (可选, 用于前端展示)
    - request_adapter: 构造下游请求(url, headers, payload) 的适配器
    - stream_adapter: 处理流式响应的适配器
    - response_adapter: 处理非流式响应的适配器 (返回 async generator)
    - models_adapter: 获取模型列表的适配器 (可选, 每个渠道可以有自己的实现)
    """

    id: str
    type_name: str
    default_base_url: Optional[str] = None
    auth_header: Optional[str] = None
    description: Optional[str] = None
    request_adapter: Optional[RequestAdapter] = None
    # 透传时构建 url/headers 的适配器（默认复用 request_adapter）
    passthrough_adapter: Optional[RequestAdapter] = None
    # 修改原因：部分渠道的透传响应格式与通用 SSE/JSON 读取器不兼容。
    # 修改方式：把透传流式和非流式响应处理器作为可选注册字段保存。
    # 目的：让 AWS Bedrock 可以在透传路径中解析自己的事件流，而不影响其他渠道。
    passthrough_stream_adapter: Optional[PassthroughStreamAdapter] = None
    passthrough_response_adapter: Optional[PassthroughResponseAdapter] = None
    stream_adapter: Optional[StreamAdapter] = None
    response_adapter: Optional[ResponseAdapter] = None
    models_adapter: Optional[ModelsAdapter] = None
    # 透传模式下对 payload 做二次修饰（保持渠道特殊逻辑在渠道文件内）
    passthrough_payload_adapter: Optional[PassthroughPayloadAdapter] = None
    supports_documents: bool = False
    supports_audio: bool = False
    default_token_url: Optional[str] = None
    # 修改原因：余额查询路由需要区分普通 API Key 渠道和 OAuth 凭据渠道。
    # 修改方式：在渠道定义上保存只读布尔标记，由具体渠道注册时声明。
    # 目的：让后端路由和前端管理页都通过统一注册表识别 OAuth 引擎。
    is_oauth: bool = False
    source: str = "plugin"
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，用于 API 响应"""
        return {
            "id": self.id,
            "type_name": self.type_name,
            "default_base_url": self.default_base_url,
            "default_token_url": self.default_token_url,
            "auth_header": self.auth_header,
            "description": self.description,
            "has_passthrough_adapter": self.passthrough_adapter is not None,
            # 修改原因：管理端需要能观察渠道是否覆盖了默认透传响应处理。
            # 修改方式：在字典输出中加入两个只读布尔标记。
            # 目的：排查 AWS Claude 透传时可确认实际使用了自定义 Bedrock 处理器。
            "has_passthrough_stream_adapter": self.passthrough_stream_adapter is not None,
            "has_passthrough_response_adapter": self.passthrough_response_adapter is not None,
            "has_models_adapter": self.models_adapter is not None,
            "supports_documents": self.supports_documents,
            "supports_audio": self.supports_audio,
            # 修改原因：管理端需要知道某个 engine 是否应走 OAuth 账号 UI 和余额分流。
            # 修改方式：把 ChannelDefinition.is_oauth 输出为只读字段。
            # 目的：前端无需继续只依赖硬编码引擎列表即可识别 OAuth 渠道。
            "is_oauth": self.is_oauth,
            "source": self.source,
        }


# 全局注册表: key 为 channel id(engine), value 为渠道定义
_REGISTRY: Dict[str, ChannelDefinition] = {}


def register_channel(
    id: str,
    type_name: str,
    default_base_url: Optional[str] = None,
    default_token_url: Optional[str] = None,
    auth_header: Optional[str] = None,
    description: Optional[str] = None,
    request_adapter: Optional[RequestAdapter] = None,
    stream_adapter: Optional[StreamAdapter] = None,
    response_adapter: Optional[ResponseAdapter] = None,
    models_adapter: Optional[ModelsAdapter] = None,
    overwrite: bool = False,
    *,
    passthrough_adapter: Optional[RequestAdapter] = None,
    passthrough_stream_adapter: Optional[PassthroughStreamAdapter] = None,
    passthrough_response_adapter: Optional[PassthroughResponseAdapter] = None,
    supports_documents: bool = False,
    supports_audio: bool = False,
    passthrough_payload_adapter: Optional[PassthroughPayloadAdapter] = None,
    # 修改原因：OAuth 渠道的凭据和余额查询都由 OAuthManager 处理，和普通 API Key 渠道不同。
    # 修改方式：register_channel 增加可选 is_oauth 参数，默认保持 False 以兼容既有渠道。
    # 目的：具体渠道只需在注册时声明一次，后续路由和前端都可读取同一标记。
    is_oauth: bool = False,
    source: str = "plugin",
) -> None:
    """
    注册一个渠道, 供 core.request / core.response 统一调度使用。
    
    Args:
        id: 渠道唯一标识
        type_name: 渠道类型名
        default_base_url: 默认的 Base URL
        auth_header: 认证头格式
        description: 渠道描述
        request_adapter: 请求适配器
        stream_adapter: 流式响应适配器
        response_adapter: 非流式响应适配器
        models_adapter: 模型列表适配器
        overwrite: 是否覆盖已存在的渠道（用于插件热重载）
    """
    if id in _REGISTRY and not overwrite:
        raise ValueError(f"Channel with id={id!r} already registered")

    _REGISTRY[id] = ChannelDefinition(
        id=id,
        type_name=type_name,
        default_base_url=default_base_url,
        default_token_url=default_token_url,
        auth_header=auth_header,
        description=description,
        request_adapter=request_adapter,
        passthrough_adapter=passthrough_adapter,
        # 修改原因：register_channel 新增的透传响应钩子必须随渠道定义一起落库。
        # 修改方式：把传入的自定义透传流式/非流式适配器写入 ChannelDefinition。
        # 目的：handler 在透传分发时可以发现并调用渠道专用处理器。
        passthrough_stream_adapter=passthrough_stream_adapter,
        passthrough_response_adapter=passthrough_response_adapter,
        passthrough_payload_adapter=passthrough_payload_adapter,
        stream_adapter=stream_adapter,
        response_adapter=response_adapter,
        models_adapter=models_adapter,
        supports_documents=supports_documents,
        supports_audio=supports_audio,
        # 修改原因：OAuth 标记是渠道定义的一部分，必须随注册参数一起保存。
        # 修改方式：把 register_channel 的 is_oauth 参数写入 ChannelDefinition。
        # 目的：余额路由可以从注册表稳定判断是否调用 OAuthManager.fetch_quota。
        is_oauth=is_oauth,
        source=source,
    )


def unregister_channel(id: str) -> bool:
    """
    注销一个渠道。
    
    Args:
        id: 渠道唯一标识
        
    Returns:
        是否成功注销（False 表示渠道不存在）
    """
    if id in _REGISTRY:
        del _REGISTRY[id]
        return True
    return False


def get_channel(id: str) -> Optional[ChannelDefinition]:
    """
    按 id(engine) 获取渠道定义, 若未注册则返回 None。
    """
    return _REGISTRY.get(id)


def list_channels() -> List[ChannelDefinition]:
    """
    返回当前已注册的所有渠道定义列表。
    """
    return list(_REGISTRY.values())


def list_channel_ids() -> List[str]:
    """
    返回当前已注册的所有渠道 ID 列表。
    """
    return list(_REGISTRY.keys())