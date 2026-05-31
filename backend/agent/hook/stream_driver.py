"""StreamDriverHook — 将 Message 流式事件广播为 SSE StreamEvent。

新设计：直接透传 Message 字段，不再翻译 kind/field 名称。
前端收到 StreamEvent 后直接 msg[ev.field] += ev.delta。
"""

from __future__ import annotations

import asyncio
import logging

from shared.hooks import BaseHook
from shared.types import Message, StreamEvent, StreamEventKind

logger = logging.getLogger(__name__)


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
        self._closed: bool = False

    # ── 订阅管理 ────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue[StreamEvent | None]:
        q: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        self._subscribers.append(q)
        if self._closed:
            q.put_nowait(None)
        return q

    def unsubscribe(self, q: asyncio.Queue[StreamEvent | None]) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def close(self) -> None:
        self._closed = True
        self.close_subscribers()

    def close_subscribers(self) -> None:
        """End current SSE subscribers without permanently closing the driver."""
        for q in self._subscribers:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
        self._subscribers.clear()

    # ── 内部广播 ─────────────────────────────────────────

    def _broadcast(self, event: StreamEvent) -> None:
        dead: list[asyncio.Queue[StreamEvent | None]] = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

    # ═══════════════════════════════════════════════════════
    # BaseHook 实现 — 直接透传 Message 字段名
    # ═══════════════════════════════════════════════════════

    async def on_message_start(self, *, msg: Message, **kwargs) -> None:
        self._broadcast(
            StreamEvent.message_start(msg.turn_id, msg.id, role=msg.role.value)
        )

    async def on_chunk_delta(
        self, *, msg: Message, field: str, delta: str, tool_name: str = "", **kwargs
    ) -> None:
        if not delta or not msg.id:
            return

        print(
            f"\n>>>> on_chunk_delta {msg.id} | {field} | {delta} | {tool_name} | {kwargs}"
        )
        tool_index = kwargs.get("tool_index", -1)
        sub_field = kwargs.get("sub_field", "")
        self._broadcast(
            StreamEvent.chunk_delta(
                msg.id,
                field,
                delta,
                tool_name=tool_name,
                tool_index=tool_index,
                sub_field=sub_field,
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
        self._broadcast(
            StreamEvent.chunk_complete(
                msg.id,
                field,
                full_content,
                tool_name=tool_name,
                tool_args=tool_args,
                is_error=is_error,
            )
        )

    async def on_message_finish(self, *, msg: Message, **kwargs) -> None:
        self._broadcast(StreamEvent.message_finish(msg.id))

    async def on_turn_end(
        self, *, turn_id: str, input_tokens: int = 0, output_tokens: int = 0, **kwargs
    ) -> None:
        if turn_id:
            self._broadcast(
                StreamEvent.turn_complete(turn_id, input_tokens, output_tokens)
            )
            self.close_subscribers()

    async def on_message_error(
        self, *, msg: Message, error: Exception, **kwargs
    ) -> None:
        self._broadcast(StreamEvent.interrupted(str(error)))
        self.close_subscribers()
