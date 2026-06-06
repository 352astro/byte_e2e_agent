"""Message lifecycle helpers for AgentRuntime."""

from __future__ import annotations

import uuid as _uuid

from shared.hooks import HookManager
from shared.types import Message


async def emit_error_message(
    hooks: HookManager,
    *,
    session_id: str,
    turn_id: str,
    error: str,
) -> Message:
    msg = Message.error_message(_uuid.uuid4().hex, turn_id, error)
    await hooks.on_message_start(msg=msg, session_id=session_id)
    await hooks.on_chunk_complete(
        msg=msg,
        field="error",
        full_content=msg.error,
        is_error=True,
        session_id=session_id,
    )
    await hooks.on_message_finish(msg=msg, session_id=session_id)
    return msg


async def emit_system_message(
    hooks: HookManager,
    *,
    session_id: str,
    turn_id: str,
    content: str,
) -> Message:
    """Emit a system message through the hook pipeline for append-only persistence.

    Returns the created Message (already persisted via PersistenceHook).
    """
    msg = Message.system_message(_uuid.uuid4().hex, turn_id, content)
    await hooks.on_message_start(msg=msg, session_id=session_id)
    await hooks.on_chunk_complete(
        msg=msg,
        field="content",
        full_content=content,
        session_id=session_id,
    )
    await hooks.on_message_finish(msg=msg, session_id=session_id)
    return msg


async def finish_partial_streaming_message(
    hooks: HookManager,
    msg: Message | None,
    *,
    session_id: str,
) -> None:
    if msg is None or not msg.id:
        return
    if not (
        msg.content or msg.reasoning or msg.error or msg.tool_result or msg.tool_calls
    ):
        return
    msg.mark_complete()
    await hooks.on_message_finish(
        msg=msg,
        session_id=session_id,
        finish_reason="interrupted",
        usage=getattr(msg, "_usage", None) or {},
    )


def extract_usage(msg: Message | None) -> dict:
    """Extract usage from a streamed Message, with a small fallback estimate."""
    if msg is None:
        return {}
    usage = getattr(msg, "_usage", None)
    if usage:
        return usage
    result = {}
    if msg.content:
        result["completion_tokens"] = len(msg.content) // 4
    return result
