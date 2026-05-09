"""
渠道注册模块

自动导入并注册所有渠道适配器
支持通过 core.plugins 插件系统动态加载外部渠道
"""

from .registry import (
    ChannelDefinition,
    RequestAdapter,
    StreamAdapter,
    ResponseAdapter,
    register_channel,
    unregister_channel,
    get_channel,
    list_channels,
    list_channel_ids,
)

# 导入各渠道模块以触发注册
from . import openai_channel
from . import openai_responses_channel
from . import gemini_channel
from . import claude_channel
from . import azure_channel
from . import aws_channel
from . import vertex_channel
from . import openrouter_channel
from . import cloudflare_channel
from . import openai_image_channel
from . import codex_channel
from . import claude_code_channel
# 修改原因：Gemini CLI OAuth 是内置渠道，需要在 channels 包导入时进入注册流程。
# 修改方式：像 Codex 和 Claude Code 一样导入自包含渠道模块。
# 目的：让 core.channels.get_channel("gemini-cli") 能被请求路由和管理端发现。
from . import gemini_cli_channel

# 调用各渠道的 register() 函数
openai_channel.register()
openai_responses_channel.register()
gemini_channel.register()
claude_channel.register()
azure_channel.register()
aws_channel.register()
vertex_channel.register()
openrouter_channel.register()
cloudflare_channel.register()
openai_image_channel.register()
codex_channel.register()
claude_code_channel.register()
# 修改原因：导入模块只加载定义，必须显式调用 register 才会写入渠道注册表。
# 修改方式：在 OAuth 内置渠道注册序列中追加 Gemini CLI。
# 目的：让 Gemini 方言透传和普通请求都可以选择 gemini-cli engine。
gemini_cli_channel.register()

__all__ = [
    # 类型定义
    "ChannelDefinition",
    "RequestAdapter",
    "StreamAdapter",
    "ResponseAdapter",
    # 注册 API
    "register_channel",
    "unregister_channel",
    "get_channel",
    "list_channels",
    "list_channel_ids",
]