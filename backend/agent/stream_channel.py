"""StreamChannel — 单个运行中 Session 的临时流式通道。

职责：
- 接受上游 chunk 并广播给下游订阅者
- 内部累积 chunk 文本（供恢复查询）
- 上游 flush 时广播完整消息并清空该 transcript_id 的缓冲

注意：Transcript 的持久化存储在 Session 中，不在此处。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass
class StreamEvent:
    """推送给 SSE 订阅者的事件。"""

    name: str  # "chunk" | "flush"
    payload: dict[str, Any]


class StreamChannel:
    """Per-execution 临时通道 — 不持久化，只做流式广播。"""

    def __init__(self) -> None:
        self._buffer: dict[str, str] = {}  # transcript_id → accumulated text
        self._subscribers: list[asyncio.Queue[StreamEvent | None]] = []
        self._closed: bool = False

    # ── write ───────────────────────────────────────────

    async def chunk(self, transcript_id: str, text: str) -> None:
        """累积增量文本并广播 chunk 事件。"""
        self._buffer[transcript_id] = self._buffer.get(transcript_id, "") + text
        await self._broadcast(
            StreamEvent(
                "chunk",
                {"transcript_id": transcript_id, "text": text},
            )
        )

    async def flush(
        self,
        transcript_id: str,
        kind: str,
        message: dict,
    ) -> None:
        """广播完整 transcript 并清空该 id 的缓冲。

        上游在完成一条 transcript（已存入 Session）后调用。
        前端看到同一 transcript_id 的 flush 事件后，
        应用该完整内容替换之前 chunk 累积的临时文本。
        """
        await self._broadcast(
            StreamEvent(
                "flush",
                {
                    "transcript_id": transcript_id,
                    "kind": kind,
                    "message": message,
                },
            )
        )
        self._buffer.pop(transcript_id, None)

    # ── read (recovery) ─────────────────────────────────

    def get_buffered(self) -> dict[str, str]:
        """返回当前所有在途 chunk 的累积文本（供恢复查询）。"""
        return dict(self._buffer)

    # ── subscribe ───────────────────────────────────────

    def subscribe(self) -> asyncio.Queue[StreamEvent | None]:
        """返回一个接收未来 stream 事件的队列。"""
        q: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        self._subscribers.append(q)
        if self._closed:
            q.put_nowait(None)
        return q

    def unsubscribe(self, q: asyncio.Queue[StreamEvent | None]) -> None:
        """移除订阅者队列。"""
        if q in self._subscribers:
            self._subscribers.remove(q)

    # ── lifecycle ───────────────────────────────────────

    def close(self) -> None:
        """向所有订阅者发送 None 哨兵以终止 SSE 连接。"""
        self._closed = True
        for q in self._subscribers:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass

    # ── internal ────────────────────────────────────────

    async def _broadcast(self, event: StreamEvent) -> None:
        dead: list[asyncio.Queue[StreamEvent | None]] = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)
