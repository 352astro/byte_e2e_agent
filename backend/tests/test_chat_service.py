"""Unit tests for ChatService domain exceptions."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.chat_service import ChatService
from app.services.errors import AgentBusy, PendingRequestNotFound, SessionNotFound


def _make_ctx(*, get_session_side_effect=None, scheduler_start_side_effect=None):
    ctx = MagicMock()
    if get_session_side_effect is not None:
        ctx.get_session.side_effect = get_session_side_effect
    else:
        ctx.get_session.return_value = MagicMock()
    if scheduler_start_side_effect is not None:
        ctx.scheduler.start.side_effect = scheduler_start_side_effect
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
        scheduler_start_side_effect=RuntimeError("Scheduler already running (state=running)")
    )
    service = ChatService(ctx)

    with pytest.raises(AgentBusy):
        service.start_chat("abc", "hello", 1)


def test_respond_raises_pending_not_found() -> None:
    ctx = _make_ctx()
    ctx.scheduler.resolve.side_effect = KeyError("No pending request: tid1")
    service = ChatService(ctx)

    with pytest.raises(PendingRequestNotFound) as exc_info:
        service.respond_to_pending("tid1", {"approved": True})

    assert exc_info.value.transcript_id == "tid1"
