"""Unit tests for ChatService domain exceptions."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.chat_service import ChatService
from app.services.errors import AgentBusy, PendingRequestNotFound, SessionNotFound


def _make_ctx(*, get_session_side_effect=None, runtime_start_side_effect=None):
    ctx = MagicMock()
    if get_session_side_effect is not None:
        ctx.get_session.side_effect = get_session_side_effect
    else:
        ctx.get_session.return_value = MagicMock()
    if runtime_start_side_effect is not None:
        ctx.runtime.start.side_effect = runtime_start_side_effect
    ctx.scoped.return_value = ctx
    ctx.stream_driver.subscribe.return_value = asyncio.Queue()
    ctx.create_runtime_session_entry.return_value = MagicMock()
    ctx.shadow_repo = MagicMock()
    return ctx


def test_start_chat_raises_session_not_found() -> None:
    ctx = _make_ctx(get_session_side_effect=KeyError("Session not found: abc"))
    service = ChatService(ctx)

    with pytest.raises(SessionNotFound) as exc_info:
        service.start_chat("abc", "hello", 1)

    assert exc_info.value.session_id == "abc"


def test_start_chat_raises_agent_busy() -> None:
    ctx = _make_ctx(
        runtime_start_side_effect=RuntimeError("Runtime already running (state=running)")
    )
    service = ChatService(ctx)
    service._locator.resolve = MagicMock(return_value=SimpleNamespace(workspace="workspace"))

    with pytest.raises(AgentBusy):
        service.start_chat("abc", "hello", 1)


@pytest.mark.asyncio
async def test_respond_raises_pending_not_found() -> None:
    ctx = _make_ctx()
    ctx.runtime.resolve.side_effect = KeyError("No pending request: tid1")
    service = ChatService(ctx)
    service._locator.resolve = MagicMock(return_value=SimpleNamespace(workspace="workspace"))

    with pytest.raises(PendingRequestNotFound) as exc_info:
        await service.respond_to_pending("sid1", "tid1", {"approved": True})

    assert exc_info.value.transcript_id == "tid1"
