"""
oai_tier — OpenAI 官方渠道 Tier 检测（被动 + 主动）

被动模式：通过响应头 x-ratelimit-limit-tokens 采集 TPM 上限。
主动模式：余额查询时缓存无数据，发 max_completion_tokens:0 探测请求从响应头采集（零 token 消耗）。
推断 OpenAI Tier 等级，并通过 balance_enricher 注入到余额查询结果中。

使用方式：
  在 provider 的 enabled_plugins 里加 "oai_tier"
  仅给 api.openai.com 的渠道启用，不要给 Azure 或其他兼容站启用
"""

from typing import Any, Dict, Optional
import json
import time

from core.log_config import logger
from core.plugins import (
    register_response_interceptor,
    unregister_response_interceptor,
    register_balance_enricher,
    unregister_balance_enricher,
)


PLUGIN_META = {
    "name": "oai_tier",
    "display_name": "OpenAI Tier 检测",
    "description": "检测 OpenAI 账户 Tier 等级（被动采集 + 主动探测）",
    "version": "1.0.0",
    "category": "interceptors",
}

PLUGIN_EXPORTS = [
    "interceptors:oai_tier_response",
    "balance_enrichers:oai_tier_balance",
]

# 修改原因：当前插件加载器读取 PLUGIN_INFO 和 EXTENSIONS，任务说明中的 PLUGIN_META/PLUGIN_EXPORTS 需要兼容现有加载协议。
# 修改方式：保留 PLUGIN_META/PLUGIN_EXPORTS，同时提供同内容的 PLUGIN_INFO/EXTENSIONS 别名。
# 目的：让插件既符合本次命名要求，又能在现有插件管理器中展示元信息和扩展声明。
PLUGIN_INFO = {
    "name": PLUGIN_META["name"],
    "version": PLUGIN_META["version"],
    "description": PLUGIN_META["description"],
    "author": "Zoaholic Team",
    "dependencies": [],
    "metadata": {
        "display_name": PLUGIN_META["display_name"],
        "category": PLUGIN_META["category"],
        "tags": ["openai", "tier", "rate-limit", "balance"],
    },
}
EXTENSIONS = PLUGIN_EXPORTS


# ==================== Tier 缓存 ====================

# key: api_key 前 12 位, value: {"tier": str, "tpm": int, "rpm": int, "updated_at": float}
_tier_cache: Dict[str, Dict[str, Any]] = {}

# 主动探测防抖: key_prefix -> last_probe_timestamp
_probe_timestamps: Dict[str, float] = {}
_PROBE_COOLDOWN = 300  # 5 分钟内不重复探测同一个 key

# TPM → Tier 映射表 (基于 OpenAI 官方文档)
# https://platform.openai.com/docs/guides/rate-limits
_TPM_TIER_MAP = [
    (10_000_000, "Tier 5"),   # 10M+
    (2_000_000, "Tier 4"),    # 2M+
    (1_000_000, "Tier 3"),    # 1M+  (实际按模型有差异，这里取主流模型)
    (450_000, "Tier 2"),      # 450K+
    (200_000, "Tier 1"),      # 200K+
    (0, "Free"),
]


def _tpm_to_tier(tpm: int) -> str:
    """根据 TPM 上限推断 Tier"""
    for threshold, tier in _TPM_TIER_MAP:
        if tpm >= threshold:
            return tier
    return "Free"


def _cache_key(api_key: str) -> str:
    """取 key 前 12 位做缓存索引"""
    return (api_key or "")[:12]


# ==================== Response Interceptor ====================

async def _oai_tier_response_interceptor(response_chunk, engine, model, is_stream):
    """从响应头被动采集 TPM/RPM"""
    try:
        from core.middleware import request_info
        info = request_info.get()
        if not info:
            return response_chunk

        headers_json = info.get("upstream_response_headers")
        if not headers_json:
            return response_chunk

        headers = json.loads(headers_json) if isinstance(headers_json, str) else headers_json

        # 修改原因：OpenAI 官方响应头中只需要 rate-limit 上限即可被动推断账户 tier。
        # 修改方式：大小写不敏感地读取 x-ratelimit-limit-tokens 和 x-ratelimit-limit-requests。
        # 目的：不额外请求 OpenAI API，也能在正常模型调用后缓存 TPM/RPM 信息。
        tpm_str = None
        rpm_str = None
        for k, v in headers.items():
            kl = k.lower()
            if kl == "x-ratelimit-limit-tokens":
                tpm_str = v
            elif kl == "x-ratelimit-limit-requests":
                rpm_str = v

        if not tpm_str:
            return response_chunk

        tpm = int(str(tpm_str).replace(",", ""))
        rpm = int(str(rpm_str).replace(",", "")) if rpm_str else None
        tier = _tpm_to_tier(tpm)

        # 修改原因：余额查询阶段拿不到上一次响应头，需要跨请求暂存被动检测结果。
        # 修改方式：用 API Key 前 12 位作为缓存索引，保存 tier、TPM、RPM、模型和更新时间。
        # 目的：后续 balance_enricher 可以按同一个 Key 把 tier 注入余额查询结果。
        api_key = info.get("_used_api_key") or ""
        ck = _cache_key(api_key)
        if ck:
            _tier_cache[ck] = {
                "tier": tier,
                "tpm": tpm,
                "rpm": rpm,
                "model": model,
                "updated_at": time.time(),
            }
            logger.debug(f"[oai_tier] Cached tier for {ck}***: {tier} (TPM={tpm})")

    except Exception as e:
        logger.debug(f"[oai_tier] Error in response interceptor: {e}")

    return response_chunk


# ==================== Active Probe ====================

async def _probe_tier(api_key: str, base_url: str = "") -> Optional[Dict[str, Any]]:
    """主动发 max_completion_tokens:0 探测请求，从 400 响应头采集 TPM/RPM（零 token 消耗）"""
    import httpx

    if not base_url:
        base_url = "https://api.openai.com/v1"

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": ""}],
        "max_completion_tokens": 0,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=headers)

        tpm_str = resp.headers.get("x-ratelimit-limit-tokens")
        rpm_str = resp.headers.get("x-ratelimit-limit-requests")

        if not tpm_str:
            return None

        tpm = int(str(tpm_str).replace(",", ""))
        rpm = int(str(rpm_str).replace(",", "")) if rpm_str else None
        tier = _tpm_to_tier(tpm)

        return {
            "tier": tier,
            "tpm": tpm,
            "rpm": rpm,
            "model": "gpt-4o-mini (probe)",
            "updated_at": time.time(),
        }
    except Exception as e:
        logger.debug(f"[oai_tier] Probe failed: {e}")
        return None


# ==================== Balance Enricher ====================

async def _oai_tier_balance_enricher(result: dict, engine: str, provider: dict) -> dict:
    """往 balance 结果里补充 tier 信息"""
    try:
        # 修改原因：provider.api 在不同入口可能是字符串、列表或单键 dict，缓存查找必须统一成真实 Key 字符串。
        # 修改方式：依次兼容 api、api_key、列表首项和单键 dict 的常见形态。
        # 目的：确保逐 Key 余额查询和旧配置格式都能匹配到 response_interceptor 写入的缓存。
        api_key = provider.get("api") or provider.get("api_key") or ""
        if isinstance(api_key, list):
            api_key = api_key[0] if api_key else ""
        if isinstance(api_key, dict) and len(api_key) == 1:
            api_key = str(next(iter(api_key.keys())))

        ck = _cache_key(str(api_key))
        cached = _tier_cache.get(ck)

        # 缓存未命中，主动探测
        if not cached and ck:
            now = time.time()
            if now - _probe_timestamps.get(ck, 0) > _PROBE_COOLDOWN:
                _probe_timestamps[ck] = now
                base_url = provider.get("base_url") or ""
                probed = await _probe_tier(str(api_key), base_url)
                if probed:
                    _tier_cache[ck] = probed
                    cached = probed
                    logger.info(f"[oai_tier] Probed tier for {ck}***: {probed['tier']} (TPM={probed['tpm']})")

        if cached:
            result["tier"] = cached["tier"]
            result["tpm"] = cached.get("tpm")
            result["rpm"] = cached.get("rpm")
            result["tier_detected_at"] = cached.get("updated_at")
            result["tier_model"] = cached.get("model")
    except Exception as e:
        logger.debug(f"[oai_tier] Error in balance enricher: {e}")

    return result


# ==================== 生命周期 ====================

def setup(manager):
    """插件加载"""
    # 修改原因：Tier 检测分为响应头采集和余额结果补充两个阶段，不能写入 oai_tools 插件。
    # 修改方式：注册 response_interceptor 采集 OpenAI rate-limit 头，再注册 balance_enricher 输出缓存字段。
    # 目的：使 oai_tier 只在渠道启用时工作，并与其他 OpenAI 兼容渠道插件解耦。
    register_response_interceptor(
        interceptor_id="oai_tier_response",
        callback=_oai_tier_response_interceptor,
        priority=200,
        plugin_name="oai_tier",
        overwrite=True,
    )
    register_balance_enricher(
        enricher_id="oai_tier_balance",
        callback=_oai_tier_balance_enricher,
        priority=100,
        plugin_name="oai_tier",
        overwrite=True,
    )
    logger.info("[oai_tier] Plugin loaded")


def teardown(manager):
    """插件卸载"""
    unregister_response_interceptor("oai_tier_response")
    unregister_balance_enricher("oai_tier_balance")
    _tier_cache.clear()
    _probe_timestamps.clear()
    logger.info("[oai_tier] Plugin unloaded")


def unload():
    teardown(None)
