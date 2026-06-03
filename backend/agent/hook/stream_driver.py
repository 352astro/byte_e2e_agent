"""StreamDriverHook — 将 Message 流式事件广播为 SSE StreamEvent。

新设计：直接透传 Message 字段，不再翻译 kind/field 名称。
前端收到 StreamEvent 后直接 msg[ev.field] += ev.delta。
"""

from __future__ import annotations

import asyncio
import json
import logging

from shared.hooks import BaseHook
from shared.hooks import GuardCheck
from shared.types import Message, StreamEvent, StreamEventKind

logger = logging.getLogger(__name__)

_MAX_BUFFERED_EVENTS_PER_SESSION = 2000


class StreamDriverHook(BaseHook):
    """SSE 广播 Hook。持有 asyncio.Queue 订阅者列表。

    用法:
        driver = StreamDriverHook()
        q = driver.subscribe()
        # runtime 运行中 ...
        driver.unsubscribe(q)
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[StreamEvent | None]] = []
        self._subscriber_sessions: dict[int, str | None] = {}
        self._event_buffers: dict[str, list[StreamEvent]] = {}
        self._closed: bool = False

    # ── 订阅管理 ────────────────────────────────────────

    def subscribe(
        self,
        session_id: str | None = None,
        *,
        replay_buffer: bool = False,
    ) -> asyncio.Queue[StreamEvent | None]:
        q: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        self._subscribers.append(q)
        self._subscriber_sessions[id(q)] = session_id
        if replay_buffer and session_id:
            for event in self._event_buffers.get(session_id, []):
                q.put_nowait(event)
        if self._closed:
            q.put_nowait(None)
        return q

    def unsubscribe(self, q: asyncio.Queue[StreamEvent | None]) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)
        self._subscriber_sessions.pop(id(q), None)

    def close(self) -> None:
        self._closed = True
        self.close_subscribers()

    def close_subscribers(self, session_id: str | None = None) -> None:
        """End current SSE subscribers without permanently closing the driver."""
        kept: list[asyncio.Queue[StreamEvent | None]] = []
        for q in self._subscribers:
            sid = self._subscriber_sessions.get(id(q))
            if session_id is not None and sid is not None and sid != session_id:
                kept.append(q)
                continue
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
        self._subscribers = kept
        self._subscriber_sessions = {
            id(q): self._subscriber_sessions.get(id(q)) for q in kept
        }

    # ── 内部广播 ─────────────────────────────────────────

    def _broadcast(self, event: StreamEvent) -> None:
        if event.session_id:
            buffer = self._event_buffers.setdefault(event.session_id, [])
            buffer.append(event)
            if len(buffer) > _MAX_BUFFERED_EVENTS_PER_SESSION:
                del buffer[: len(buffer) - _MAX_BUFFERED_EVENTS_PER_SESSION]

        dead: list[asyncio.Queue[StreamEvent | None]] = []
        for q in self._subscribers:
            session_id = self._subscriber_sessions.get(id(q))
            if session_id is not None and event.session_id != session_id:
                continue
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    def _clear_buffer(self, session_id: str | None) -> None:
        if session_id:
            self._event_buffers.pop(session_id, None)

    # ═══════════════════════════════════════════════════════
    # BaseHook 实现 — 直接透传 Message 字段名
    # ═══════════════════════════════════════════════════════

    async def on_message_start(self, *, msg: Message, **kwargs) -> None:
        session_id = kwargs.get("session_id", "")
        self._broadcast(
            StreamEvent.message_start(
                msg.turn_id, msg.id, role=msg.role.value, session_id=session_id
            )
        )

    async def on_chunk_delta(
        self, *, msg: Message, field: str, delta: str, tool_name: str = "", **kwargs
    ) -> None:
        if not delta or not msg.id:
            return
        tool_index = kwargs.get("tool_index", -1)
        sub_field = kwargs.get("sub_field", "")
        session_id = kwargs.get("session_id", "")
        self._broadcast(
            StreamEvent.chunk_delta(
                msg.id,
                field,
                delta,
                tool_name=tool_name,
                tool_index=tool_index,
                sub_field=sub_field,
                session_id=session_id,
            )
        )

    async def on_chunk_complete(
        self,
        *,
        msg: Message,
        field: str,
        full_content: str,
        tool_name: str = "",
        tool_args: str = "",
        is_error: bool = False,
        **kwargs,
    ) -> None:
        if not msg.id:
            return
        session_id = kwargs.get("session_id", "")
        self._broadcast(
            StreamEvent.chunk_complete(
                msg.id,
                field,
                full_content,
                tool_name=tool_name,
                tool_args=tool_args,
                is_error=is_error,
                session_id=session_id,
            )
        )

    async def on_message_finish(self, *, msg: Message, **kwargs) -> None:
        session_id = kwargs.get("session_id", "")
        self._broadcast(StreamEvent.message_finish(msg.id, session_id=session_id))

    async def on_turn_end(
        self, *, turn_id: str, input_tokens: int = 0, output_tokens: int = 0, **kwargs
    ) -> None:
        if turn_id:
            session_id = kwargs.get("session_id", "")
            self._broadcast(
                StreamEvent.turn_complete(
                    turn_id, input_tokens, output_tokens, session_id=session_id
                )
            )
            self.close_subscribers(session_id=session_id)
            self._clear_buffer(session_id)

    async def on_message_error(
        self, *, msg: Message, error: Exception, **kwargs
    ) -> None:
        session_id = kwargs.get("session_id", "")
        self._broadcast(StreamEvent.interrupted(str(error), session_id=session_id))
        self.close_subscribers(session_id=session_id)
        self._clear_buffer(session_id)

    async def on_subagent_start(self, **kwargs) -> None:
        parent_session_id = kwargs.get("parent_session_id", "")
        parent_message_id = kwargs.get("parent_message_id", "")
        parent_tool_call_id = kwargs.get("parent_tool_call_id", "")
        child_session_id = kwargs.get("child_session_id", "")
        if not parent_session_id or not parent_message_id or not child_session_id:
            return
        payload = {
            "type": "subagent",
            "status": "running",
            "child_session_id": child_session_id,
            "parent_tool_call_id": parent_tool_call_id,
            "task": kwargs.get("task", ""),
            "max_steps": kwargs.get("max_steps", 0),
        }
        self._broadcast(
            StreamEvent.chunk_complete(
                parent_message_id,
                "tool_meta",
                json.dumps(payload, ensure_ascii=False),
                tool_name="SubAgent",
                session_id=parent_session_id,
            )
        )

    async def on_subagent_end(self, **kwargs) -> None:
        parent_session_id = kwargs.get("parent_session_id", "")
        parent_message_id = kwargs.get("parent_message_id", "")
        parent_tool_call_id = kwargs.get("parent_tool_call_id", "")
        child_session_id = kwargs.get("child_session_id", "")
        if not parent_session_id or not parent_message_id or not child_session_id:
            return
        payload = {
            "type": "subagent",
            "status": "complete",
            "child_session_id": child_session_id,
            "parent_tool_call_id": parent_tool_call_id,
        }
        self._broadcast(
            StreamEvent.chunk_complete(
                parent_message_id,
                "tool_meta",
                json.dumps(payload, ensure_ascii=False),
                tool_name="SubAgent",
                session_id=parent_session_id,
            )
        )

    async def on_guard_request(
        self,
        *,
        request_id: str,
        check: GuardCheck,
        **kwargs,
    ) -> None:
        payload = {
            "request_id": request_id,
            "action_type": check.action_type,
            "subject": check.subject,
            "payload": check.payload,
            "turn_id": check.turn_id,
            "message_id": check.message_id,
            "tool_call_id": check.tool_call_id,
        }
        self._broadcast(
            StreamEvent.guard_request(
                request_id,
                json.dumps(payload, ensure_ascii=False),
                session_id=check.session_id,
            )
        )
