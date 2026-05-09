# Zoaholic OAuth 凭据管理方案

## 一、概述

为 Zoaholic 新增对订阅式 CLI 工具（Claude Code、OpenAI Codex、Antigravity/Gemini CLI）的原生 OAuth 凭据管理支持。用户通过 OAuth 登录授权后，Zoaholic 自动维护 access_token / refresh_token 生命周期，对外暴露为标准 API 渠道。

## 二、新增渠道引擎

| 引擎 ID | type_name | 透传方言 | 上游默认地址 | 认证方式 |
|---------|-----------|---------|------------|---------|
| `claude-code` | `"claude"` | Claude 方言 | `https://api.anthropic.com/v1` | `Authorization: Bearer {access_token}` |
| `codex` | `"openai"` | OpenAI 方言 | `https://api.openai.com/v1` | `Authorization: Bearer {access_token}` |
| `antigravity` | `"gemini"` | Gemini 方言 | `https://generativelanguage.googleapis.com/v1beta` | `Authorization: Bearer {access_token}` |

每个引擎作为核心渠道（`core/channels/` 目录），不是插件：
- **复用现有渠道的 request/stream/response adapter**（claude_channel / openai_channel / gemini_channel）
- 只重写 headers 构建（Bearer 认证）和 passthrough adapter
- 注册 `type_name` 让对应方言自动匹配透传

## 三、数据存储设计

### 3.1 api.yaml — 只存占位 ID

```yaml
- provider: "CC-Accounts"
  engine: claude-code
  api:
    - "alice@gmail.com"
    - "bob@outlook.com"
  model:
    - claude-sonnet-4
    - claude-opus-4
  # base_url 不填 = 内置默认
  # 填了 = 打自定义反代

- provider: "Codex-Pool"
  engine: codex
  api:
    - "dev@company.com"
  model:
    - gpt-5-codex
    - codex-mini

- provider: "Gemini-CLI"
  engine: antigravity
  api:
    - "user@gmail.com"
  model:
    - gemini-3-pro
```

`api` 列表中的字符串只是标识符（邮箱或自定义 ID），映射到 `data/oauth_state.json` 中的实际凭据。如果标识符在 `oauth_state.json` 中找不到，则当作传统静态 key 原样透传（向后兼容）。

### 3.2 data/oauth_state.json — 运行时凭据

```json
{
  "alice@gmail.com": {
    "type": "claude-code",
    "access_token": "at_xxx",
    "refresh_token": "rt_xxx",
    "id_token": "eyJ...",
    "expires_at": 1715200000,
    "email": "alice@gmail.com",
    "status": "active",
    "last_refresh": "2026-05-08T19:00:00Z",
    "error_count": 0,
    "cooldown_until": null
  },
  "dev@company.com": {
    "type": "codex",
    "access_token": "at_zzz",
    "refresh_token": "rt_zzz",
    "id_token": "eyJ...",
    "account_id": "org-xxx",
    "expires_at": 1715200000,
    "email": "dev@company.com",
    "status": "active",
    "last_refresh": "2026-05-08T18:45:00Z",
    "error_count": 0,
    "cooldown_until": null
  }
}
```

### 3.3 写入时机

`oauth_state.json` 写入：
- access_token 刷新成功后
- 新账号 OAuth 登录完成后
- 账号状态变更时（cooldown / 恢复）
- 进程优雅关闭时（SIGTERM）

`api.yaml` **永远不动**（不存 token，不触发 uvicorn 热重载）。

## 四、核心模块

### 4.1 目录结构

```
core/
  oauth/
    __init__.py              # 导出 OAuthManager
    manager.py               # OAuthManager 主类
    state.py                 # oauth_state.json 读写
    providers/
      __init__.py            # Provider 注册表
      base.py                # OAuthProvider 抽象基类
      claude_code.py         # Anthropic OAuth2
      codex.py               # OpenAI OAuth2
      antigravity.py         # Google OAuth2
```

### 4.2 OAuthProvider 抽象基类

```python
class OAuthProvider(ABC):
    """OAuth 提供商抽象"""

    @abstractmethod
    async def refresh_token(self, credential: dict) -> dict:
        """刷新 access_token。返回更新后的凭据对象。"""
        ...

    @abstractmethod
    def build_auth_url(self, state: str, redirect_uri: str) -> str:
        """构建 OAuth 授权 URL"""
        ...

    @abstractmethod
    async def exchange_code(self, code: str, redirect_uri: str) -> dict:
        """授权码换 token"""
        ...

    @abstractmethod
    def get_default_base_url(self) -> str:
        """返回上游默认地址"""
        ...
```

### 4.3 OAuthManager

核心职责：
- `init()` — 启动时加载 `data/oauth_state.json` 到内存
- `resolve(key_id: str) -> str | None` — key → access_token（含自动刷新）
- `register(key_id, type, token_data)` — 注册新账号
- `persist()` — 内存 → `data/oauth_state.json`

### 4.4 Token 解析位置

**关键设计决定**：`.next()` 继续只返回账号标识符（如 `alice@gmail.com`），**不**返回 access_token。

原因：现有的重试、冷却、统计、key 禁用逻辑全是拿 `.next()` 返回值当作「配置中的 key」来操作的。如果返回 access_token，会导致：
- 日志统计记录令牌明文
- 冷却对象变成临时 token（下次刷新就对不上）
- provider_key_index 找不到
- 自动禁用对象错误

Token 解析在 **handler 层**完成：`process_request` 和 `process_request_passthrough` 中，拿到 key_id 后调 `oauth_manager.resolve(key_id)` 换 access_token，然后传给 channel adapter。日志和冷却系统看到的始终是标识符。

`OAuthManager` 挂在 `app.state` 上（不是全局单例），在 handler 层通过 request/app 上下文获取。

## 五、渠道注册

每个 OAuth 渠道注册为独立核心引擎，复用对应的原生渠道 adapter：

```python
# 以 codex 渠道为例 (core/channels/codex_channel.py)
from core.channels.openai_channel import (
    get_gpt_payload,
    fetch_gpt_response,
    fetch_gpt_response_stream,
)

async def get_codex_payload(request, engine, provider, api_key=None):
    """复用 openai channel 的 payload 构建，替换认证头"""
    url, headers, payload = await get_gpt_payload(request, "openai", provider, api_key)
    headers["Authorization"] = f"Bearer {api_key}"
    return url, headers, payload

async def get_codex_passthrough_meta(request, engine, provider, api_key=None):
    """透传 meta：构建 URL + Bearer 头"""
    from ..utils import resolve_base_url
    base_url = provider.get('base_url') or "https://api.openai.com/v1"
    url = resolve_base_url(base_url, '/chat/completions')
    headers = {
        "content-type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    return url, headers, {}

def register():
    from .registry import register_channel
    register_channel(
        id="codex",
        type_name="openai",
        default_base_url="https://api.openai.com/v1",
        auth_header="Authorization: Bearer {api_key}",
        description="OpenAI Codex (OAuth subscription)",
        request_adapter=get_codex_payload,
        passthrough_adapter=get_codex_passthrough_meta,
        response_adapter=fetch_gpt_response,
        stream_adapter=fetch_gpt_response_stream,
    )
```

claude-code 和 antigravity 同理，分别复用 claude_channel 和 gemini_channel。

## 六、OAuth 登录流

### 6.1 后端路由 (routes/oauth.py)

```
GET  /v1/oauth/authorize?type=codex       → 返回 auth_url
GET  /v1/oauth/callback?code=...&state=... → 换 token，存 state
POST /v1/oauth/import                      → 手动导入 refresh_token
GET  /v1/oauth/accounts                    → 列出所有 OAuth 账号
DELETE /v1/oauth/accounts/{key_id}         → 删除账号
```

所有端点挂 `verify_admin_api_key` 鉴权。

### 6.2 登录流程

1. 前端调 `GET /v1/oauth/authorize?type=codex` → 后端返回授权 URL
2. 用户浏览器跳转授权页登录 → 回调到 `GET /v1/oauth/callback`
3. 后端拿到 code → 换 token → 存 state.json → 返回邮箱/ID
4. 前端把邮箱填进渠道的 api 列表

### 6.3 手动导入

支持从 CLIProxyAPI `auths/` 目录或本地配置文件复制 refresh_token：
```
POST /v1/oauth/import
{
  "key_id": "dev@company.com",
  "type": "codex",
  "refresh_token": "rt_xxxx"
}
```

## 七、各 Provider 要点

### 7.1 Claude Code (Anthropic)
- PKCE 必须，Token Rotation，~1h 有效期
- 需要 Claude Code 特征 UA/billing（复用 claude_code_compat 插件）
- `anthropic-beta: oauth-2025-04-20`

### 7.2 Codex (OpenAI)
- Auth0 hosted OAuth，PKCE 必须，Token Rotation
- ~1h 有效期，5h/7d quota window
- JWT 含 account_id

### 7.3 Antigravity (Google/Gemini CLI)
- Google 标准 OAuth2，refresh_token 通常不轮换
- ~1h 有效期，Antigravity 固定 client_id/secret

## 八、安全

- `oauth_state.json` 文件权限 600，加入 .gitignore
- OAuth callback 用 state 参数做 CSRF 防护（5 分钟过期）
- 所有 `/v1/oauth/*` 端点挂 admin 鉴权
- 日志里只记 key_id（邮箱），不记 access_token

## 九、实施顺序

### Phase 1 — MVP: Codex 单渠道
1. `core/oauth/` 模块（manager + state + codex provider）
2. `core/channels/codex_channel.py` 渠道注册
3. `routes/oauth.py` 手动导入端点
4. handler 层 token 解析集成
5. 测试：手动导入 refresh_token → 自动刷新 → 请求通

### Phase 2 — Claude Code + Antigravity
6. claude_code provider + claude-code 渠道
7. antigravity provider + antigravity 渠道

### Phase 3 — 前端 + 登录流
8. OAuth 登录按钮 + authorize/callback 完整流程
9. OAuth 账号状态展示
10. 手动导入弹窗

### Phase 4 — 增强
11. 配额检测 & 展示
12. 批量导入
13. 账号健康度定时检测
