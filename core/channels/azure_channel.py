"""
Azure OpenAI 渠道适配器

负责处理 Azure OpenAI API 的请求构建和响应流解析

API Key 格式支持：
- 纯 key: "sk-xxxxxxxx" — 需要手动配 base_url
- resource:key: "myresource:sk-xxxxxxxx" — 自动拼 base_url
  反代也支持: base_url 配 "https://workers.dev/{resource}.openai.azure.com"
  {resource} 会被替换成冒号前的部分
"""

import asyncio
import urllib.parse
from datetime import datetime

from ..utils import (
    safe_get,
    get_model_dict,
    get_base64_image,
    get_tools_mode,
    generate_sse_response,
    end_of_line,
)
from ..response import check_response
from ..json_utils import json_loads, json_dumps_text
from ..response_context import mark_adapter_metrics_managed, mark_content_start, merge_usage
from ..stream_utils import aiter_decoded_lines
from ..usage import extract_cache_usage


# ============================================================
# Azure OpenAI 格式化函数
# ============================================================

DEFAULT_BASE_URL = "https://{resource}.openai.azure.com"


def format_text_message(text: str) -> dict:
    """格式化文本消息为 Azure OpenAI 格式"""
    return {"type": "text", "text": text}


async def format_image_message(image_url: str) -> dict:
    """格式化图片消息为 Azure OpenAI 格式"""
    base64_image, _ = await get_base64_image(image_url)
    return {
        "type": "image_url",
        "image_url": {
            "url": base64_image,
        }
    }


def _parse_resource_key(api_key: str, base_url: str):
    """解析 resource:key 格式，返回 (实际 api_key, 最终 base_url)。

    支持三种场景：
    1. 纯 key（无冒号）→ base_url 不变
    2. resource:key → base_url 里的 {resource} 占位符被替换
    3. resource:key + 反代 base_url → 同样替换 {resource}
    """
    api_key_str = str(api_key or "")
    if ":" not in api_key_str:
        return api_key_str, base_url

    resource, real_key = api_key_str.split(":", 1)
    resource = resource.strip()
    real_key = real_key.strip()

    if not resource or not real_key:
        return api_key_str, base_url

    # 替换 base_url 中的 {resource} 占位符
    if "{resource}" in base_url:
        resolved_url = base_url.replace("{resource}", resource)
    else:
        # base_url 没有占位符，可能是直接写了完整 URL，不做替换
        resolved_url = base_url

    return real_key, resolved_url


def build_azure_endpoint(base_url, deployment_id, api_version=None):
    """构建 Azure OpenAI 端点 URL。

    优先使用 v1 API 路径（不需要 api-version 参数）。
    如果用户配了 api_version，回退到旧路径格式。
    """
    base_url = base_url.rstrip('/')

    # 如果 URL 已经包含完整路径（如用户用 # 锁定），直接返回
    if "models/chat/completions" in base_url or base_url.endswith("#"):
        return base_url.rstrip("#")

    if api_version:
        # 旧路径：/openai/deployments/{id}/chat/completions?api-version=xxx
        path = f"/openai/deployments/{deployment_id}/chat/completions"
        final_url = urllib.parse.urljoin(base_url + "/", path.lstrip("/"))
        if "?api-version=" not in final_url:
            final_url = f"{final_url}?api-version={api_version}"
        return final_url
    else:
        # v1 新路径：/openai/v1/chat/completions（不需要 api-version）
        # deployment 通过 payload 里的 model 字段传递
        path = "/openai/v1/chat/completions"
        return urllib.parse.urljoin(base_url + "/", path.lstrip("/"))


async def get_azure_payload(request, engine, provider, api_key=None):
    """构建 Azure OpenAI API 的请求 payload"""
    model_dict = get_model_dict(provider)
    original_model = model_dict[request.model]

    # 解析 resource:key 格式
    real_key, resolved_url = _parse_resource_key(api_key, provider.get('base_url', DEFAULT_BASE_URL))

    # 读取用户配置的 api_version（如果有）
    api_version = safe_get(provider, "preferences", "api_version", default=None)

    headers = {
        'Content-Type': 'application/json',
        'api-key': real_key,
    }

    url = build_azure_endpoint(
        base_url=resolved_url,
        deployment_id=original_model,
        api_version=api_version,
    )

    messages = []
    for msg in request.messages:
        tool_calls = None
        tool_call_id = None
        if isinstance(msg.content, list):
            content = []
            for item in msg.content:
                if item.type == "text":
                    text_message = format_text_message(item.text)
                    content.append(text_message)
                elif item.type == "image_url" and provider.get("image", True) and "o1-mini" not in original_model:
                    image_message = await format_image_message(item.image_url.url)
                    content.append(image_message)
        else:
            content = msg.content
            tool_calls = msg.tool_calls
            tool_call_id = msg.tool_call_id

        if tool_calls:
            tools_mode = get_tools_mode(provider)
            if tools_mode != "none":
                tool_calls_list = []
                # 根据 tools_mode 决定处理多少个工具调用
                calls_to_process = tool_calls if tools_mode == "parallel" else tool_calls[:1]
                for tool_call in calls_to_process:
                    tool_calls_list.append({
                        "id": tool_call.id,
                        "type": tool_call.type,
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    })
                messages.append({"role": msg.role, "tool_calls": tool_calls_list})
        elif tool_call_id:
            tools_mode = get_tools_mode(provider)
            if tools_mode != "none":
                messages.append({"role": msg.role, "tool_call_id": tool_call_id, "content": content})
        else:
            messages.append({"role": msg.role, "content": content})

    payload = {
        "model": original_model,
        "messages": messages,
    }

    miss_fields = [
        'model',
        'messages',
    ]

    for field, value in request.model_dump(exclude_unset=True).items():
        if field not in miss_fields and value is not None:
            if field == "max_tokens" and "o1" in original_model:
                payload["max_completion_tokens"] = value
            else:
                payload[field] = value

    tools_mode = get_tools_mode(provider)
    if tools_mode == "none" or "o1" in original_model or "chatgpt-4o-latest" in original_model or "grok" in original_model:
        payload.pop("tools", None)
        payload.pop("tool_choice", None)

    return url, headers, payload


async def fetch_azure_response(client, url, headers, payload, model, timeout):
    """处理 Azure OpenAI 非流式响应"""
    json_payload = await asyncio.to_thread(json_dumps_text, payload)
    response = await client.post(url, headers=headers, content=json_payload, timeout=timeout)
    
    error_message = await check_response(response, "fetch_azure_response")
    if error_message:
        yield error_message
        return

    response_bytes = await response.aread()
    response_json = await asyncio.to_thread(json_loads, response_bytes)
    mark_adapter_metrics_managed()
    usage = response_json.get("usage", {}) if isinstance(response_json, dict) else {}
    # Azure OpenAI 返回 OpenAI 兼容 usage；这里同步支持 prompt_tokens_details.cached_tokens。
    merge_usage(
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
        **extract_cache_usage(usage),
    )
    if safe_get(response_json, "choices", 0, "message", "content", default=None):
        mark_content_start()
    
    # 删除 content_filter_results
    if "choices" in response_json:
        for choice in response_json["choices"]:
            if "content_filter_results" in choice:
                del choice["content_filter_results"]

    # 删除 prompt_filter_results
    if "prompt_filter_results" in response_json:
        del response_json["prompt_filter_results"]

    yield response_json


async def fetch_azure_response_stream(client, url, headers, payload, model, timeout):
    """处理 Azure OpenAI 流式响应"""
    timestamp = int(datetime.timestamp(datetime.now()))
    is_thinking = False
    has_send_thinking = False
    ark_tag = False
    json_payload = await asyncio.to_thread(json_dumps_text, payload)
    async with client.stream('POST', url, headers=headers, content=json_payload, timeout=timeout) as response:
        error_message = await check_response(response, "fetch_azure_response_stream")
        if error_message:
            yield error_message
            return

        mark_adapter_metrics_managed()
        sse_string = ""
        async for line in aiter_decoded_lines(response.aiter_bytes()):
                if line and not line.startswith(":") and (result:=line.lstrip("data: ").strip()):
                    if result.strip() == "[DONE]":
                        break
                    line = json_loads(result)
                    no_stream_content = safe_get(line, "choices", 0, "message", "content", default="")
                    content = safe_get(line, "choices", 0, "delta", "content", default="")

                    # 处理 <think> 标签
                    if "<think>" in content:
                        is_thinking = True
                        ark_tag = True
                        content = content.replace("<think>", "")
                    if "</think>" in content:
                        is_thinking = False
                        content = content.replace("</think>", "")
                        if not content:
                            continue
                    if is_thinking and ark_tag:
                        if not has_send_thinking:
                            content = content.replace("\n\n", "")
                        if content:
                            mark_content_start()
                            sse_string = await generate_sse_response(timestamp, payload["model"], reasoning_content=content)
                            yield sse_string
                            has_send_thinking = True
                        continue

                    if no_stream_content or content or sse_string:
                        input_tokens = safe_get(line, "usage", "prompt_tokens", default=0)
                        output_tokens = safe_get(line, "usage", "completion_tokens", default=0)
                        total_tokens = safe_get(line, "usage", "total_tokens", default=0)
                        if no_stream_content or content:
                            mark_content_start()
                        usage = safe_get(line, "usage", default={}) or {}
                        cache_usage = extract_cache_usage(usage)
                        if total_tokens or input_tokens or output_tokens:
                            # 流式 usage chunk 中可能带缓存命中信息，需要与普通 token 同步写入 current_info 和下游响应。
                            merge_usage(
                                prompt_tokens=input_tokens,
                                completion_tokens=output_tokens,
                                total_tokens=total_tokens,
                                **cache_usage,
                            )
                        sse_string = await generate_sse_response(
                            timestamp, safe_get(line, "model", default=None),
                            content=no_stream_content or content,
                            total_tokens=total_tokens,
                            prompt_tokens=input_tokens,
                            completion_tokens=output_tokens,
                            cached_tokens=cache_usage["cached_tokens"],
                            cache_creation_tokens=cache_usage["cache_creation_tokens"],
                        )
                        yield sse_string
                    else:
                        if no_stream_content:
                            del line["choices"][0]["message"]
                        json_line = json_dumps_text(line, ensure_ascii=False)
                        yield "data: " + json_line.strip() + end_of_line
    yield "data: [DONE]" + end_of_line


async def fetch_azure_models(client, provider):
    """获取 Azure OpenAI 的模型列表（数据平面 API）。

    使用 GET {endpoint}/openai/models 端点，api-key 认证。
    返回该 Azure 资源下所有可用模型。
    """
    raw_base_url = provider.get('base_url', DEFAULT_BASE_URL)
    api_key = provider.get('api')
    if isinstance(api_key, list):
        api_key = api_key[0] if api_key else None

    # 解析 resource:key
    real_key, resolved_url = _parse_resource_key(api_key, raw_base_url)

    # {resource} 还在说明没有 resource:key 格式也没手动填 base_url
    if "{resource}" in resolved_url:
        raise ValueError("Azure 渠道需要配置 resource:key 格式的 API Key 或手动指定 base_url")

    resolved_url = resolved_url.rstrip('/')
    # 数据平面模型列表端点
    models_url = f"{resolved_url}/openai/models?api-version=2024-10-21"

    headers = {
        'Content-Type': 'application/json',
        'api-key': real_key,
    }

    response = await client.get(models_url, headers=headers)
    response.raise_for_status()

    data = response.json()
    models = []
    if isinstance(data, dict) and 'data' in data:
        for m in data['data']:
            if isinstance(m, dict) and m.get('id'):
                models.append(m['id'])
    elif isinstance(data, list):
        models = [m.get('id') if isinstance(m, dict) else m for m in data]

    return models


def register():
    """注册 Azure 渠道到注册中心"""
    from .registry import register_channel

    register_channel(
        id="azure",
        type_name="openai-responses",
        default_base_url=DEFAULT_BASE_URL,
        auth_header="api-key: {api_key}",
        description="Azure OpenAI Service",
        request_adapter=get_azure_payload,
        response_adapter=fetch_azure_response,
        stream_adapter=fetch_azure_response_stream,
        models_adapter=fetch_azure_models,
        source="builtin",
    )
