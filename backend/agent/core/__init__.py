"""core 包 — 核心抽象。"""

from agent.core.config import (
    AccessPolicy,
    AgentConfig,
    InvokePermission,
    Lifecycle,
    Owner,
    SessionConfig,
    ToolSetPreset,
    Visibility,
)
from agent.core.prompts import SYSTEM_PROMPT
from agent.core.workspace import Workspace
from shared.hooks import BaseHook, HookManager
from shared.types import (
    Message,
    MessageRole,
    MessageStatus,
    StreamEvent,
    StreamEventKind,
    ToolCall,
    ToolCallFunction,
    Turn,
)

__all__ = [
    # types
    "Message",
    "MessageRole",
    "MessageStatus",
    "StreamEvent",
    "StreamEventKind",
    "ToolCall",
    "ToolCallFunction",
    "Turn",
    # hooks
    "BaseHook",
    "HookManager",
    # config
    "AccessPolicy",
    "AgentConfig",
    "InvokePermission",
    "Lifecycle",
    "Owner",
    "SessionConfig",
    "ToolSetPreset",
    "Visibility",
    # workspace
    "Workspace",
    # prompts
    "SYSTEM_PROMPT",
]
