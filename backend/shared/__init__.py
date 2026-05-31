"""Shared types and infrastructure — not agent-specific.

Types defined here are the single source of truth for both backend and frontend.
"""

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
    "Message",
    "MessageRole",
    "MessageStatus",
    "StreamEvent",
    "StreamEventKind",
    "ToolCall",
    "ToolCallFunction",
    "Turn",
]
