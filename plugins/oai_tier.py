"""
oai_tier — OpenAI 官方渠道 Tier 被动检测

通过响应头 x-ratelimit-limit-tokens 被动采集 TPM 上限，
推断 OpenAI Tier 等级，并通过 balance_enricher 注入到余额查询结果中。

使用方式：
  在 provider 的 enabled_plugins 里加 "oai_tier"
  仅给 api.openai.com 的渠道启用，不要给 Azure 或其他兼容站启用
"""

from typing import Any, Dict
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
    "description": "被动检测 OpenAI 账户 Tier 等级",
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
        api_key = info.get("api_key") or info.get("original_api_key") or ""
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
    logger.info("[oai_tier] Plugin unloaded")


def unload():
    teardown(None)
