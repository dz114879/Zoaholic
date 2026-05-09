"""OAuth 凭据管理器。"""

import asyncio
import inspect
import json
import logging
import os
import tempfile
from datetime import datetime, timezone

from .state import STATE_PATH, load_state

logger = logging.getLogger(__name__)


class OAuthManager:
    """负责 key_id 到 access_token 的解析、刷新和持久化。"""

    def __init__(self, state_path: str = STATE_PATH):
        # 修改原因：OAuth 凭据属于运行时状态，不能写入 api.yaml 或普通 provider 配置。
        # 修改方式：manager 维护内存 state、每账号刷新锁和 provider 注册表。
        # 目的：让 handler 只解析 access_token，不改变现有轮询、冷却和统计使用的 key_id。
        self._state = {}
        self._locks = {}
        self._providers = {}
        self._state_path = state_path
        self._pkce_store = {}
        # 修改原因：OAuthManager 生命周期长于 api.yaml 配置，provider 需要在调用时读取当前 app.state.config。
        # 修改方式：保存一个配置获取函数引用，而不是保存某次启动时的配置副本。
        # 目的：前端保存 token_url 后，下一次刷新或授权码交换能立即使用新配置。
        self._config_ref = None
        # 修改原因：Codex 被动额度采集会在普通请求路径频繁触发，不能每次更新都同步写磁盘。
        # 修改方式：用 generation 标记内存 quota 是否变更，并用 30 秒 call_later 定时器批量持久化。
        # 目的：让 quota 缓存能尽快服务前端，同时避免高频请求放大 oauth_state.json 写入。
        self._quota_update_generation = 0
        self._quota_persisted_generation = 0
        self._quota_persist_handle = None
        self._quota_flush_delay = 30

    def register_provider(self, type_name: str, provider):
        """注册 OAuth provider。渠道 register() 或插件 setup() 中调用。"""
        self._providers[type_name] = provider
        # 修改原因：部分调用路径仍会直接使用 provider，例如 authorize 路由需要读取 redirect_mode 和构建授权 URL。
        # 修改方式：如果 provider 支持 set_config_getter，就注入 manager.get_config 作为运行时配置读取入口。
        # 目的：即使调用方没有显式传 config，CodexProvider 也能解析到最新 token_url。
        if hasattr(provider, "set_config_getter"):
            provider.set_config_getter(self.get_config)

    def set_config_ref(self, config_getter):
        """设置配置获取函数。main.py lifespan 调用。"""
        # 修改原因：main.py 持有 app.state.config，而 OAuth 子模块不应反向导入 main.app 以避免循环导入。
        # 修改方式：由 lifespan 把 lambda: app.state.config or {} 注入到 manager。
        # 目的：让 OAuth provider 每次请求前都能通过 manager 获取当前运行时配置。
        self._config_ref = config_getter

    def get_config(self) -> dict:
        """获取当前运行时配置。"""
        # 修改原因：配置引用可能在测试、启动早期或异常状态下不可调用或返回非 dict。
        # 修改方式：调用前检查 callable，调用后只接受 dict，任何异常都回退为空配置。
        # 目的：保证 OAuth 刷新路径失败时最多回退默认 token endpoint，不因配置引用异常崩溃。
        if not callable(self._config_ref):
            return {}
        try:
            config = self._config_ref()
        except Exception:
            return {}
        return config if isinstance(config, dict) else {}

    async def init(self):
        """加载状态文件。provider 注册由各渠道/插件自行调用 register_provider 完成。"""
        self._state = load_state(self._state_path)

    async def resolve(self, key_id: str) -> str | None:
        """把配置中的 key_id 解析成 access_token；不存在时返回 None。"""
        cred = self._state.get(key_id)
        if not cred:
            return None

        # 修改原因：连续 refresh 失败的账号会在请求路径中反复触发上游错误和本地落盘。
        # 修改方式：解析前检查 error_count 和最近失败时间，5 分钟熔断窗口内直接返回 None。
        # 目的：让 handler 可以切换其他 key，同时避免坏 refresh_token 放大失败影响。
        if self._is_refresh_circuit_open(cred):
            return None

        import time

        if time.time() > cred.get("expires_at", 0) - 300:
            async with self._get_lock(key_id):
                cred = self._state.get(key_id)
                if not cred:
                    return None
                if self._is_refresh_circuit_open(cred):
                    return None
                if time.time() > cred.get("expires_at", 0) - 300:
                    try:
                        cred = await self._refresh(key_id, cred)
                    except Exception as e:
                        # 修改原因：刷新失败若不写回状态，下一次请求会立刻重复同样的失败刷新。
                        # 修改方式：累加 error_count，截断保存 last_error，并尽力持久化错误状态。
                        # 目的：让账号进入可观测的 error 状态，并让上层 handler 跳过当前 key。
                        error_count = cred.get("error_count", 0) + 1
                        cred["error_count"] = error_count
                        cred["last_error"] = str(e)[:500]
                        cred["last_error_at"] = datetime.utcnow().isoformat() + "Z"
                        cred["status"] = "error"
                        self._state[key_id] = cred
                        try:
                            await self._persist()
                        except Exception:
                            pass
                        logger.warning(f"OAuth refresh failed for {key_id} (attempt {error_count}): {e}")
                        return None
        return cred.get("access_token")

    def _is_refresh_circuit_open(self, cred: dict) -> bool:
        """判断账号是否处于 refresh 失败熔断窗口。"""
        # 修改原因：resolve 进入锁前后都需要同一套熔断判断，复制逻辑容易造成阈值不一致。
        # 修改方式：把“失败 5 次且最近 5 分钟内失败过”的判断集中到一个小函数。
        # 目的：保持请求前快速跳过坏账号，并兼顾并发刷新等待后的二次检查。
        error_count = cred.get("error_count", 0)
        if error_count < 5:
            return False
        last_error_at = cred.get("last_error_at", "")
        if not last_error_at:
            return False
        try:
            last_err_time = datetime.fromisoformat(last_error_at.replace("Z", "+00:00"))
            if last_err_time.tzinfo is None:
                last_err_time = last_err_time.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - last_err_time).total_seconds() < 300
        except (ValueError, TypeError):
            return False

    async def _refresh(self, key_id: str, cred: dict) -> dict:
        """刷新单个 OAuth 凭据并落盘。"""
        provider = self._providers.get(cred.get("type"))
        if not provider:
            raise ValueError(f"Unknown OAuth type: {cred.get('type')}")
        updated = await self._call_provider_method(provider.refresh_token, cred)
        updated["last_refresh"] = datetime.utcnow().isoformat() + "Z"
        updated["status"] = "active"
        updated["error_count"] = 0
        updated.setdefault("type", cred.get("type"))
        updated.setdefault("email", cred.get("email"))

        # 修改原因：OpenAI refresh token rotation 成功后，若落盘失败，磁盘旧 refresh_token 可能已失效。
        # 修改方式：写入新内存状态前保存旧值，_persist 抛错时恢复旧状态或移除新增 key。
        # 目的：保证内存与磁盘在持久化失败时保持一致，避免运行期继续依赖未成功保存的新 token。
        old_cred = self._state.get(key_id)
        self._state[key_id] = updated
        try:
            await self._persist()
        except Exception:
            if old_cred is not None:
                self._state[key_id] = old_cred
            else:
                self._state.pop(key_id, None)
            raise
        return updated

    async def refresh_provider(self, type_name: str, credential: dict) -> dict:
        """调用指定 provider 刷新凭据，并传入当前配置。"""
        # 修改原因：routes.oauth 的手动导入路径也会直接刷新 token，不能绕过实时配置读取机制。
        # 修改方式：统一通过 _call_provider_method 调用 provider.refresh_token。
        # 目的：让后台自动刷新和手动导入刷新使用同一套 config 注入规则。
        provider = self._providers.get(type_name)
        if not provider:
            raise ValueError(f"Unknown OAuth type: {type_name}")
        return await self._call_provider_method(provider.refresh_token, credential)

    async def exchange_code(
        self,
        type_name: str,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> dict:
        """调用指定 provider 交换授权码，并传入当前配置。"""
        # 修改原因：OAuth 登录交换和 refresh 一样访问 token endpoint，也需要使用最新 token_url。
        # 修改方式：由 manager 根据 type_name 找到 provider，并通过 _call_provider_method 注入当前 config。
        # 目的：避免 routes.oauth 直接调用 provider 时遗漏运行时配置。
        provider = self._providers.get(type_name)
        if not provider:
            raise ValueError(f"Unknown OAuth type: {type_name}")
        return await self._call_provider_method(
            provider.exchange_code,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )

    def _method_accepts_config(self, method) -> bool:
        """判断 provider 方法是否接受 config 参数。"""
        # 修改原因：历史测试替身和后续第三方 provider 可能仍使用旧签名，直接传 config 会导致 TypeError。
        # 修改方式：通过 inspect.signature 判断是否声明 config 或 **kwargs。
        # 目的：在不破坏旧 provider 的前提下，为新 provider 提供运行时配置。
        try:
            parameters = inspect.signature(method).parameters.values()
        except (TypeError, ValueError):
            return False
        return any(
            parameter.name == "config" or parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )

    async def _call_provider_method(self, method, *args, **kwargs):
        """调用 provider 方法，并在其支持时注入当前配置。"""
        # 修改原因：OAuthProvider 基类已支持可选 config，但旧 provider 或测试替身不一定同步更新签名。
        # 修改方式：只在目标方法声明 config 或 **kwargs 时添加 config=self.get_config()。
        # 目的：兼容旧实现，同时让 CodexProvider 每次调用都拿到最新 app.state.config。
        call_kwargs = dict(kwargs)
        if self._method_accepts_config(method) and "config" not in call_kwargs:
            call_kwargs["config"] = self.get_config()
        result = method(*args, **call_kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def _get_cached_quota(self, cred: dict) -> dict | None:
        """从 oauth_state 凭据中读取已缓存 quota。"""
        # 修改原因：Codex 普通响应会被动写入 quota，前端按需查询时应优先使用缓存而不是再消耗一次上游请求。
        # 修改方式：只读取顶层 quota_5h、quota_7d 和 quota_raw，并把 quota_raw 映射回接口返回的 raw 字段。
        # 目的：保持 list_accounts 可直接展示百分比，同时让 /quota 返回结构与主动查询一致。
        if not isinstance(cred, dict):
            return None
        result = {}
        if cred.get("quota_5h") is not None:
            result["quota_5h"] = cred.get("quota_5h")
        if cred.get("quota_7d") is not None:
            result["quota_7d"] = cred.get("quota_7d")
        if isinstance(cred.get("quota_raw"), dict):
            result["raw"] = cred.get("quota_raw")
        return result if result else None

    async def fetch_quota(self, key_id: str) -> dict | None:
        """获取账号额度信息。"""
        # 修改原因：quota 查询是 provider 可选能力，OAuthManager 需要统一查找账号、provider 并注入当前配置。
        # 修改方式：先返回被动采集缓存；缓存不存在时，再通过 provider 发起轻量主动查询并写入内存缓存。
        # 目的：减少上游额度探测请求，同时让路由和前端不需要了解各 OAuth provider 的额度实现差异。
        cred = self._state.get(key_id)
        if not cred:
            return None
        cached = self._get_cached_quota(cred)
        if cached:
            return cached
        provider = self._providers.get(cred.get("type"))
        if not provider or not hasattr(provider, "fetch_quota"):
            return None
        quota = await self._call_provider_method(provider.fetch_quota, cred)
        if isinstance(quota, dict):
            self.update_quota(key_id, quota)
            return quota
        return None

    def update_quota(self, key_id: str, quota_data: dict) -> bool:
        """更新 OAuth 账号的 quota 内存缓存，并安排延迟落盘。"""
        # 修改原因：Codex 响应 wrapper 会在普通请求完成时拿到最新 x-ratelimit-*，这些数据要回写到 OAuthManager state。
        # 修改方式：只更新内存中的目标账号字段，使用 quota_raw 保存原始 header，并标记 generation 后调度 30 秒批量持久化。
        # 目的：让被动采集的数据可被 /v1/oauth/accounts 和 /quota 读取，同时避免每次请求都写文件。
        if not isinstance(quota_data, dict):
            return False
        cred = self._state.get(key_id)
        if not isinstance(cred, dict):
            return False

        changed = False
        for field in ("quota_5h", "quota_7d"):
            if field in quota_data and quota_data.get(field) is not None:
                if cred.get(field) != quota_data.get(field):
                    cred[field] = quota_data.get(field)
                    changed = True
        if isinstance(quota_data.get("raw"), dict) and cred.get("quota_raw") != quota_data.get("raw"):
            cred["quota_raw"] = dict(quota_data["raw"])
            changed = True

        if not changed:
            return False
        cred["quota_updated_at"] = datetime.utcnow().isoformat() + "Z"
        self._quota_update_generation += 1
        self._schedule_quota_persist()
        return True

    def _schedule_quota_persist(self) -> None:
        """启动或复用 quota 延迟落盘定时器。"""
        # 修改原因：update_quota 是同步方法，可能从响应 adapter 中被频繁调用，不能直接 await 持久化。
        # 修改方式：在当前事件循环中用 call_later 安排一次 flush；没有运行事件循环时只保留 dirty 标记。
        # 目的：运行服务中自动批量落盘，单元测试或同步上下文中不制造悬挂任务。
        if self._quota_persist_handle is not None and not self._quota_persist_handle.cancelled():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        def _run_flush():
            self._quota_persist_handle = None
            asyncio.create_task(self._flush_quota_updates())

        self._quota_persist_handle = loop.call_later(self._quota_flush_delay, _run_flush)

    async def _flush_quota_updates(self) -> None:
        """把 quota dirty generation 批量写入 oauth_state.json。"""
        # 修改原因：定时器触发时可能已经有多次 quota 更新，持久化只需要写一次完整 state。
        # 修改方式：记录本次 flush 覆盖的 generation，写盘完成后若期间又有新更新则重新安排下一次 flush。
        # 目的：保证最终落盘不丢更新，同时仍维持批量写入行为。
        generation = self._quota_update_generation
        if generation <= self._quota_persisted_generation:
            return
        await self._persist()
        self._quota_persisted_generation = max(self._quota_persisted_generation, generation)
        if self._quota_update_generation > generation:
            self._schedule_quota_persist()

    async def register(self, key_id: str, type_name: str, token_data: dict):
        """注册或覆盖一个 OAuth 账号。"""
        # 修改原因：手动导入 refresh_token 后需要形成完整 oauth_state 条目。
        # 修改方式：复制传入 token_data，补齐 type、状态和错误计数后持久化。
        # 目的：避免路由层传入的原始 body 被原地修改，也让列表和解析逻辑获得统一字段。
        saved = dict(token_data or {})
        saved["type"] = type_name
        saved["status"] = "active"
        saved["error_count"] = 0
        self._state[key_id] = saved
        await self._persist()

    async def rename(self, old_key_id: str, new_key_id: str):
        """重命名 OAuth 账号标识符。"""
        # 修改原因：前端重命名 api_keys 中的 OAuth 标识符后，oauth_state.json 仍保留旧 key 会导致 access_token 解析失败。
        # 修改方式：在内存 state 中把旧 key 的凭据迁移到新 key，同时迁移同账号刷新锁并重新持久化。
        # 目的：让 api.yaml 中的新账号标识和 OAuth 运行时状态保持一致。
        if old_key_id not in self._state:
            raise ValueError(f"Account not found: {old_key_id}")
        if new_key_id in self._state and new_key_id != old_key_id:
            raise ValueError(f"Account already exists: {new_key_id}")
        cred = self._state.pop(old_key_id)
        self._state[new_key_id] = cred
        if old_key_id in self._locks:
            self._locks[new_key_id] = self._locks.pop(old_key_id)
        await self._persist()

    def list_accounts(self) -> dict:
        """列出 OAuth 账号，并隐藏 token 明文。"""
        # 修改原因：管理接口需要展示账号状态，但不能把 access_token 和 refresh_token 暴露给前端或日志。
        # 修改方式：返回 state 的浅拷贝，并把敏感 token 字段替换为星号。
        # 目的：降低凭据泄露风险，同时保留排查状态所需的非敏感字段。
        return {
            k: {**v, "access_token": "***", "refresh_token": "***"}
            for k, v in self._state.items()
        }

    async def remove(self, key_id: str):
        """移除一个 OAuth 账号。"""
        self._state.pop(key_id, None)
        await self._persist()

    async def _persist(self):
        """原子写 oauth_state.json，避免阻塞事件循环。"""
        # 修改原因：refresh token rotation 后直接 open("w") 写正式文件，进程崩溃可能截断 oauth_state.json。
        # 修改方式：把 JSON 序列化、临时文件写入、fsync 和 os.replace 放在线程中执行，事件循环只等待结果。
        # 目的：确保刷新后的凭据要么完整替换旧文件，要么保留旧文件，不产生半写入状态。
        await asyncio.to_thread(self._write_state_atomic)

    def _write_state_atomic(self) -> None:
        """同步执行 oauth_state.json 原子写。"""
        # 修改原因：os.replace 只有在同目录临时文件上才能可靠保持原子替换语义。
        # 修改方式：在状态文件同目录创建 .tmp 文件，写入并 fsync 后再替换正式路径。
        # 目的：降低机器断电、进程崩溃或写盘异常导致 OAuth 凭据永久损坏的风险。
        data = json.dumps(self._state, indent=2, ensure_ascii=False)
        state_path = self._state_path
        dir_path = os.path.dirname(state_path) or "."
        os.makedirs(dir_path, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, state_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        try:
            os.chmod(state_path, 0o600)
        except OSError:
            pass

    def _get_lock(self, key_id: str):
        """按账号创建刷新锁，防止并发刷新同一个 refresh_token。"""
        if key_id not in self._locks:
            self._locks[key_id] = asyncio.Lock()
        return self._locks[key_id]
