import json
from pathlib import Path
import sys

import pytest

# 修改原因：本测试会直接导入 routes 与 core 模块，单文件运行时项目根目录可能不在 sys.path 中。
# 修改方式：从测试文件向上查找同时包含 core/ 和 routes/ 的目录，并在缺失时插入导入路径。
# 目的：让 OAuth 余额入口回归测试在完整测试集和单文件测试两种方式下都能稳定运行。
ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if (parent / "core").is_dir() and (parent / "routes").is_dir()
)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _json_response_payload(response) -> dict:
    """读取 FastAPI JSONResponse 的 JSON 内容。"""
    # 修改原因：余额路由直接返回 JSONResponse，测试不能依赖 ASGI 客户端才能读取响应体。
    # 修改方式：对 response.body 解码后用 json.loads 还原为 dict。
    # 目的：让路由分流测试只关注返回结构，不引入额外 HTTP 测试栈。
    return json.loads(response.body.decode())


def test_channel_definition_exposes_oauth_marker():
    from core.channels.registry import get_channel, register_channel, unregister_channel

    # 修改原因：余额路由需要从渠道注册表判断某个 engine 是否由 OAuth 凭据驱动。
    # 修改方式：注册一个临时 OAuth 渠道，断言 ChannelDefinition 和 to_dict 都暴露 is_oauth。
    # 目的：保证后端和前端都能通过统一渠道定义识别 OAuth 引擎。
    engine = "oauth-balance-test-registry"
    unregister_channel(engine)
    try:
        register_channel(id=engine, type_name="openai", is_oauth=True)
        channel = get_channel(engine)
        assert channel is not None
        assert channel.is_oauth is True
        assert channel.to_dict()["is_oauth"] is True
    finally:
        unregister_channel(engine)


def test_codex_channel_is_registered_as_oauth():
    from core.channels import get_channel

    # 修改原因：Codex 渠道的余额应走 OAuthManager.fetch_quota，而不是普通 preferences.balance 配置。
    # 修改方式：读取启动时已注册的 codex 渠道定义，检查 OAuth 标记。
    # 目的：防止后续重构注册参数时丢失 Codex 的 OAuth 余额分流能力。
    channel = get_channel("codex")
    assert channel is not None
    assert channel.is_oauth is True
    assert channel.to_dict()["is_oauth"] is True


@pytest.mark.asyncio
async def test_oauth_channel_balance_uses_oauth_manager_and_merges_results(monkeypatch):
    from core.channels.registry import register_channel, unregister_channel
    from routes import channels as channels_route

    # 修改原因：OAuth 渠道没有 preferences.balance，余额入口必须直接遍历 provider.api 中的账号标识查询 quota。
    # 修改方式：注册临时 OAuth engine，并用假的 OAuthManager 记录 fetch_quota 调用和返回不同账号结果。
    # 目的：固定 /v1/channels/balance 对 OAuth 渠道的统一入口行为，同时保持返回结构可被现有余额展示读取。
    engine = "oauth-balance-test-route"
    unregister_channel(engine)

    class OAuthManager:
        def __init__(self):
            self.calls: list[str] = []

        async def fetch_quota(self, key_id: str):
            self.calls.append(key_id)
            if key_id == "alpha@example.com":
                return {"quota_5h": 80.0, "quota_7d": 60.0, "raw": {"reset_requests": "10m"}}
            if key_id == "beta@example.com":
                return {"quota_5h": 40.0}
            return None

    oauth_manager = OAuthManager()
    app = type(
        "App",
        (),
        {"state": type("State", (), {"oauth_manager": oauth_manager, "config": {}})()},
    )()
    monkeypatch.setattr(channels_route, "get_app", lambda: app)

    try:
        register_channel(id=engine, type_name="openai", is_oauth=True)
        response = await channels_route.query_channel_balance(
            token="admin",
            provider_config={
                "engine": engine,
                "api": ["alpha@example.com", "beta@example.com", "missing@example.com"],
                "preferences": {},
            },
        )
    finally:
        unregister_channel(engine)

    payload = _json_response_payload(response)
    assert oauth_manager.calls == ["alpha@example.com", "beta@example.com", "missing@example.com"]
    assert payload["supported"] is True
    assert payload["value_type"] == "percent"
    assert payload["percent"] == 40.0
    assert payload["available"] == 40.0
    assert payload["total"] == 100.0
    assert payload["error"] is None
    assert payload["results"] == {
        "alpha@example.com": {
            "supported": True,
            "value_type": "percent",
            "total": 100.0,
            "used": 40.0,
            "available": 60.0,
            "percent": 60.0,
            "quota_5h": 80.0,
            "quota_7d": 60.0,
            "raw": {"reset_requests": "10m"},
            "error": None,
        },
        "beta@example.com": {
            "supported": True,
            "value_type": "percent",
            "total": 100.0,
            "used": 60.0,
            "available": 40.0,
            "percent": 40.0,
            "quota_5h": 40.0,
            "quota_7d": None,
            "raw": None,
            "error": None,
        },
        "missing@example.com": {
            "supported": True,
            "value_type": "percent",
            "total": None,
            "used": None,
            "available": None,
            "percent": None,
            "quota_5h": None,
            "quota_7d": None,
            "raw": None,
            "error": "OAuth 额度不可用",
        },
    }


@pytest.mark.asyncio
async def test_oauth_channel_balance_returns_single_key_shape(monkeypatch):
    from core.channels.registry import register_channel, unregister_channel
    from routes import channels as channels_route

    # 修改原因：现有前端按单个 Key 调用余额接口，并把响应直接当作 BalanceResult 存入对应行。
    # 修改方式：用 api_key 字符串请求 OAuth 余额，断言顶层直接包含 percent 与 quota 字段，同时保留 results 映射。
    # 目的：让新 OAuth 分流不破坏旧的逐 Key 余额展示数据形状。
    engine = "oauth-balance-test-single"
    unregister_channel(engine)

    class OAuthManager:
        async def fetch_quota(self, key_id: str):
            assert key_id == "solo@example.com"
            return {"quota_5h": 90.0, "quota_7d": 70.0}

    app = type(
        "App",
        (),
        {"state": type("State", (), {"oauth_manager": OAuthManager(), "config": {}})()},
    )()
    monkeypatch.setattr(channels_route, "get_app", lambda: app)

    try:
        register_channel(id=engine, type_name="openai", is_oauth=True)
        response = await channels_route.query_channel_balance(
            token="admin",
            provider_config={"engine": engine, "api_key": "solo@example.com", "preferences": {}},
        )
    finally:
        unregister_channel(engine)

    payload = _json_response_payload(response)
    assert payload["supported"] is True
    assert payload["value_type"] == "percent"
    assert payload["percent"] == 70.0
    assert payload["available"] == 70.0
    assert payload["quota_5h"] == 90.0
    assert payload["quota_7d"] == 70.0
    assert payload["results"]["solo@example.com"]["percent"] == 70.0
