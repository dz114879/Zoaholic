"""
Key 入站防护插件：UA 白名单 + tools 剥离

通过参数配置允许的 User-Agent 关键词列表，只有匹配任意一个的请求才放行，
其余全部 403 拒绝。同时可选剥离 tools/tool_choice。

参数格式（冒号后逗号分隔）：
  ua:关键词        → 添加一个允许的 UA 关键词（不区分大小写）
  no_tools         → 关闭 tools 剥离（默认开启）
  strip_tools      → 开启 tools 剥离（默认）

没有配 ua: 参数时不检测 UA，所有客户端放行。
配了 ua: 参数后，只有 UA 包含任意一个关键词的请求才放行。

示例：
  enabled_plugins:
    - "key_guard"                                          → 只剥离 tools，不检测 UA
    - "key_guard:ua:sillytavern"                           → 只允许酒馆 + 剥离 tools
    - "key_guard:ua:sillytavern,ua:kobold"                 → 允许酒馆和 kobold
    - "key_guard:ua:sillytavern,ua:chatbox,no_tools"       → 允许酒馆和 chatbox，不剥离 tools
    - "key_guard:ua:curl,ua:python-requests"               → 只允许 curl 和 python requests
"""

import logging
from fastapi import HTTPException
from core.plugins.interceptors import register_inbound_interceptor

PLUGIN_INFO = {
    "name": "key_guard",
    "version": "1.0.0",
    "description": "Key 入站防护：UA 白名单 + tools 剥离",
    "author": "Zoaholic",
    "dependencies": [],
    "metadata": {
        "category": "interceptors",
        "params_hint": "UA 白名单多个关键词用 | 分隔；Tools 剥离默认开启。旧格式 ua:sillytavern,ua:chatbox,no_tools 仍兼容。",
        "params_schema": [
            {
                "key": "allowed_ua",
                "label": "UA 白名单",
                "type": "text",
                "default": "",
                "placeholder": "sillytavern|chatbox|kobold",
                "serialize": "key_value",
            },
            {
                "key": "strip_tools",
                "label": "剥离 tools",
                "type": "toggle",
                "default": True,
                "serialize": "key_value",
            },
        ],
    },
}

logger = logging.getLogger("Zoaholic")


def _split_ua_keywords(value: str) -> list:
    """拆分 UA 关键词。新格式使用 | 分隔，旧手写配置也兼容分号和空白。"""
    normalized = value.replace(';', '|').replace('\n', '|')
    return [item.strip().lower() for item in normalized.split('|') if item.strip()]


def _parse_bool(value: str, default: bool = True) -> bool:
    text = str(value or '').strip().lower()
    if text in {'1', 'true', 'yes', 'on', 'strip_tools'}:
        return True
    if text in {'0', 'false', 'no', 'off', 'no_tools'}:
        return False
    return default


def _parse_opts(enabled_plugins: list) -> tuple:
    """解析参数，返回 (allowed_ua_keywords: list[str], do_strip_tools: bool)"""
    allowed_ua = []
    do_strip_tools = True

    if not enabled_plugins:
        return allowed_ua, do_strip_tools

    for ep in enabled_plugins:
        if ep == 'key_guard':
            continue
        if not ep.startswith('key_guard:'):
            continue
        parts = ep.split(':', 1)[1].split(',')
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if part.startswith('ua:'):
                kw = part[3:].strip().lower()
                if kw:
                    allowed_ua.append(kw)
            elif part.startswith('allowed_ua='):
                allowed_ua.extend(_split_ua_keywords(part.split('=', 1)[1]))
            elif part.startswith('ua='):
                allowed_ua.extend(_split_ua_keywords(part.split('=', 1)[1]))
            elif part.startswith('strip_tools='):
                do_strip_tools = _parse_bool(part.split('=', 1)[1], default=do_strip_tools)
            elif part.startswith('tools='):
                do_strip_tools = _parse_bool(part.split('=', 1)[1], default=do_strip_tools)
            elif part == 'no_tools':
                do_strip_tools = False
            elif part == 'strip_tools':
                do_strip_tools = True

    # 去重并保持顺序，避免重复配置导致日志过长。
    allowed_ua = list(dict.fromkeys(allowed_ua))
    return allowed_ua, do_strip_tools


def _get_ua(request) -> str:
    if request is None:
        return ''
    try:
        return dict(request.headers).get('user-agent', '').lower()
    except Exception:
        return ''


def _strip_tools(request_data):
    if hasattr(request_data, 'tools'):
        request_data.tools = None
    if hasattr(request_data, 'tool_choice'):
        request_data.tool_choice = None
    if isinstance(request_data, dict):
        request_data.pop('tools', None)
        request_data.pop('tool_choice', None)


async def key_guard_interceptor(request_data, request, api_key_info, enabled_plugins):
    if request_data is None:
        return request_data

    allowed_ua, do_strip_tools = _parse_opts(enabled_plugins)
    api_key = (api_key_info.get('api_key', '???') if api_key_info else '???')[:15]

    # UA 白名单检测
    if allowed_ua:
        ua = _get_ua(request)
        matched = any(kw in ua for kw in allowed_ua)
        if not matched:
            logger.warning(f"[key_guard] UA not in whitelist for key {api_key}... (UA: {ua[:80]}), allowed: {allowed_ua}")
            raise HTTPException(
                status_code=403,
                detail="This API key does not allow requests from this client."
            )

    # Tools 剥离
    if do_strip_tools:
        has_tools = False
        if hasattr(request_data, 'tools') and request_data.tools:
            has_tools = True
        elif isinstance(request_data, dict) and request_data.get('tools'):
            has_tools = True
        if has_tools:
            _strip_tools(request_data)
            logger.info(f"[key_guard] Stripped tools for key {api_key}...")

    return request_data


register_inbound_interceptor(
    "key_guard",
    key_guard_interceptor,
    priority=30,
    plugin_name="key_guard",
    metadata={
        "description": "Key 入站防护：UA 白名单 + tools 剥离",
        "stage": "inbound_interceptors",
        "params_hint": PLUGIN_INFO["metadata"]["params_hint"],
        "params_schema": PLUGIN_INFO["metadata"]["params_schema"],
    },
)
