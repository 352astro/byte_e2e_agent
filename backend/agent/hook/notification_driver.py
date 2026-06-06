"""NotificationDriverHook — global SSE broadcast for guard requests, notices, subagent lifecycle.

Unlike StreamDriverHook (per-session filtered), this hook broadcasts to all subscribers
regardless of session_id. The session_id is carried in the payload for UX routing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from shared.hooks import BaseHook, GuardCheck
from shared.types import StreamEvent

logger = logging.getLogger(__name__)

_MAX_BUFFERED_EVENTS_PER_KIND = 500


class NotificationDriverHook(BaseHook):
    """Global notification broadcaster. No per-session filtering."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[StreamEvent | None]] = []
        self._closed: bool = False

        # ── Recoverable state ─────────────────────────
        self._pending_guard: dict | None = None
        self._notices: list[dict] = []
        self._active_subagents: dict[str, dict] = {}

        # ── Event buffers for replay on subscribe ─────
        self._event_buffers: dict[str, list[StreamEvent]] = {}

    # ── Subscriber management ─────────────────────────────

    def subscribe(
        self,
        *,
        replay_buffer: bool = False,
    ) -> asyncio.Queue[StreamEvent | None]:
        """Create a new subscriber queue.

        Returns a queue that receives all notification StreamEvents
        plus a final None sentinel on unsubscribe/close.
        """
        q: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        self._subscribers.append(q)
        if replay_buffer:
            for kind in ("guard_request", "runtime_notice", "subagent"):
                for event in self._event_buffers.get(kind, []):
                    q.put_nowait(event)
        if self._closed:
            q.put_nowait(None)
        return q

    def unsubscribe(self, q: asyncio.Queue[StreamEvent | None]) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def close(self) -> None:
        self._closed = True
        self._close_all_subscribers()

    def _close_all_subscribers(self) -> None:
        for q in self._subscribers:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
        self._subscribers.clear()

    # ── Broadcast ─────────────────────────────────────────

    def _broadcast(self, event: StreamEvent, *, kind: str) -> None:
        """Push event to all subscribers. No session_id filtering."""
        # Buffer for replay
        buffer = self._event_buffers.setdefault(kind, [])
        buffer.append(event)
        if len(buffer) > _MAX_BUFFERED_EVENTS_PER_KIND:
            del buffer[: len(buffer) - _MAX_BUFFERED_EVENTS_PER_KIND]

        dead: list[asyncio.Queue[StreamEvent | None]] = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    # ── BaseHook: guard_request ───────────────────────────

    async def on_guard_request(
        self,
        *,
        request_id: str,
        check: GuardCheck,
        **kwargs: Any,
    ) -> None:
        payload = {
            "kind": "guard_request",
            "request_id": request_id,
            "action_type": check.action_type,
            "subject": check.subject,
            "payload": check.payload,
            "session_id": check.session_id,
            "turn_id": check.turn_id,
            "message_id": check.message_id,
            "tool_call_id": check.tool_call_id,
        }
        self._pending_guard = payload

        event = StreamEvent.guard_request(
            request_id,
            json.dumps(payload, ensure_ascii=False),
            session_id=check.session_id,
        )
        self._broadcast(event, kind="guard_request")

    # ── BaseHook: runtime_notice ──────────────────────────

    async def on_runtime_notice(
        self,
        *,
        notice_id: str,
        level: str = "info",
        title: str = "Runtime notice",
        detail: str = "",
        progress: str = "",
        retry_after_ms: int = 0,
        retry_at: int = 0,
        ttl_ms: int = 4500,
        sticky: bool = False,
        **kwargs: Any,
    ) -> None:
        session_id = kwargs.get("session_id", "")
        now_ms = int(time.time() * 1000)
        record = {
            "notice_id": notice_id,
            "level": level,
            "title": title,
            "detail": detail,
            "progress": progress,
            "retry_after_ms": retry_after_ms,
            "retry_at": retry_at,
            "ttl_ms": ttl_ms,
            "sticky": sticky,
            "session_id": session_id,
            "created_at_ms": now_ms,
        }
        self._notices.append(record)
        # Prune expired non-sticky notices
        self._notices = [
            n for n in self._notices if n["sticky"] or (now_ms - n["created_at_ms"]) < n["ttl_ms"]
        ]

        event = StreamEvent.runtime_notice(
            notice_id,
            level=level,
            title=title,
            detail=detail,
            progress=progress,
            retry_after_ms=retry_after_ms,
            retry_at=retry_at,
            ttl_ms=ttl_ms,
            sticky=sticky,
            session_id=session_id,
            turn_id=kwargs.get("turn_id", ""),
            message_id=kwargs.get("message_id", ""),
        )
        self._broadcast(event, kind="runtime_notice")

    # ── BaseHook: subagent lifecycle ──────────────────────

    async def on_subagent_start(self, **kwargs: Any) -> None:
        parent_session_id = kwargs.get("parent_session_id", "")
        child_session_id = kwargs.get("child_session_id", "")
        parent_message_id = kwargs.get("parent_message_id", "")
        parent_tool_call_id = kwargs.get("parent_tool_call_id", "")
        task = kwargs.get("task", "")
        max_steps = kwargs.get("max_steps", 0)

        if child_session_id:
            self._active_subagents[child_session_id] = {
                "child_session_id": child_session_id,
                "parent_session_id": parent_session_id,
                "parent_message_id": parent_message_id,
                "parent_tool_call_id": parent_tool_call_id,
                "task": task,
                "max_steps": max_steps,
                "status": "running",
            }

        payload = {
            "type": "subagent",
            "status": "running",
            "child_session_id": child_session_id,
            "parent_session_id": parent_session_id,
            "parent_tool_call_id": parent_tool_call_id,
            "task": task,
            "max_steps": max_steps,
        }
        event = StreamEvent.chunk_complete(
            parent_message_id,
            "tool_meta",
            json.dumps(payload, ensure_ascii=False),
            tool_name="SubAgent",
            session_id=parent_session_id,
        )
        self._broadcast(event, kind="subagent")

    async def on_subagent_end(self, **kwargs: Any) -> None:
        child_session_id = kwargs.get("child_session_id", "")
        parent_session_id = kwargs.get("parent_session_id", "")
        parent_message_id = kwargs.get("parent_message_id", "")
        parent_tool_call_id = kwargs.get("parent_tool_call_id", "")

        if child_session_id in self._active_subagents:
            self._active_subagents[child_session_id]["status"] = "complete"

        payload = {
            "type": "subagent",
            "status": "complete",
            "child_session_id": child_session_id,
            "parent_session_id": parent_session_id,
            "parent_tool_call_id": parent_tool_call_id,
        }
        event = StreamEvent.chunk_complete(
            parent_message_id,
            "tool_meta",
            json.dumps(payload, ensure_ascii=False),
            tool_name="SubAgent",
            session_id=parent_session_id,
        )
        self._broadcast(event, kind="subagent")

    # ── Recover ───────────────────────────────────────────

    def build_recover_payload(self) -> dict:
        """Return current state for /api/notifications/recover."""
        return {
            "pending_guard": self._pending_guard,
            "notices": self._notices,
            "active_subagents": list(self._active_subagents.values()),
        }

    def resolve_guard(self, request_id: str) -> None:
        """Clear pending guard after resolution."""
        if self._pending_guard and self._pending_guard.get("request_id") == request_id:
            self._pending_guard = None
