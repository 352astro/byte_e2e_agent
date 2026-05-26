"""Transcript — 一等存储单元 + 构建完成器。

每个 Transcript 代表会话中一个不可分割的事件。
id 贯穿该事件的整个生命周期（chunk/flush/respond 均以此为 key）。

StreamTranscriptCompletion 是"最新一条构建中 Transcript"的唯一真相源：
- chunk() 逐步填充子流
- flush() 收尾 → 广播 SSE → 返回完整 Transcript 供持久化
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

# ── Kind 定义 ─────────────────────────────────────────────

TranscriptKind = Literal[
    "user_question",
    "assistant",
    "tool_result",
    "permission_request",
    "permission_response",
    "error",
    "commit_attachment",
]


# ── 纯净的存储单元 ───────────────────────────────────────


@dataclass
class Transcript:
    """A single event in a session timeline."""

    id: str  # UUID, unique across the session
    kind: TranscriptKind
    message: dict = field(default_factory=dict)
    commit_sha: str = ""  # non-empty when a shadow commit is attached


# ── 构建过程中的子流（StreamTranscriptCompletion 内部类型）─


@dataclass
class SubStream:
    """Transcript 构建过程中的一个子流阶段。

    例如一次 assistant 响应可能依次经历：
      thinking → response → tool_name(tc/0) → tool_arguments(tc/0) → tool_result(tr/0)
    每个阶段是一个 SubStream。
    """

    id: str
    kind: str  # thinking | response | tool_name | tool_arguments | tool_result
    text: str


# ── SSE 事件 ──────────────────────────────────────────────


@dataclass
class StreamEvent:
    """推送给 SSE 订阅者的事件。"""

    name: str  # "chunk" | "flush"
    payload: dict[str, Any]


# ── 完成器 ────────────────────────────────────────────────


class StreamTranscriptCompletion:
    """Per-execution：维护一条构建中 Transcript 并广播。

    用法:
        completion = StreamTranscriptCompletion()
        q = completion.subscribe()
        # ... start running task ...

        # 流式写入
        await completion.chunk(tid, "thinking", token)
        await completion.chunk(tid, "tool_name", "Shell", chunk_id=f"{tid}/tc/0")

        # 收尾 — 返回完整 Transcript 供调用方 add_transcript
        t = await completion.flush(tid, "assistant", message)
        session.add_transcript(t.kind, t.message, t.id)
    """

    def __init__(self) -> None:
        self._transcript: Transcript | None = None
        self._sub_streams: list[SubStream] = []
        self._active: SubStream | None = None
        self._subscribers: list[asyncio.Queue[StreamEvent | None]] = []
        self._closed: bool = False

    # ── helpers ──────────────────────────────────────────

    def _build_payload(self) -> dict[str, Any]:
        """序列化当前 Transcript + sub_streams 为广播 payload。"""
        t = self._transcript
        if t is None:
            return {}
        ss = self._sub_streams.copy()
        if self._active:
            ss.append(self._active)
        result = {
            "transcript_id": t.id,
            "kind": t.kind,
            "message": t.message,
            "sub_streams": [{"id": s.id, "kind": s.kind, "text": s.text} for s in ss],
            "active_sub_stream": None,
        }
        if t.commit_sha:
            result["commit_sha"] = t.commit_sha
        return result

    # ── write ────────────────────────────────────────────

    async def chunk(
        self,
        transcript_id: str,
        kind: str,
        text: str,
        chunk_id: str = "",
    ) -> None:
        cid = chunk_id or transcript_id

        if self._transcript is None:
            self._transcript = Transcript(id=transcript_id, kind="assistant")

        # Auto-flush: id 或 kind 变动
        if self._active and (self._active.id != cid or self._active.kind != kind):
            self._sub_streams.append(self._active)
            self._active = None

        # 更新 active
        if self._active and self._active.id == cid and self._active.kind == kind:
            self._active.text += text
        else:
            self._active = SubStream(id=cid, kind=kind, text=text)

        await self._broadcast(
            StreamEvent(
                "chunk",
                {
                    "transcript_id": transcript_id,
                    "id": cid,
                    "kind": kind,
                    "text": text,
                },
            )
        )

    async def flush(
        self,
        transcript_id: str,
        kind: str,
        message: dict | None = None,
        commit_sha: str = "",
    ) -> Transcript:
        """收尾当前 Transcript 并广播。

        返回构建完成的 Transcript，调用方应使用它进行 add_transcript。
        """
        if self._transcript is None:
            self._transcript = Transcript(id=transcript_id, kind=kind)

        t = self._transcript

        # 收尾 active
        if self._active:
            self._sub_streams.append(self._active)
            self._active = None

        t.kind = kind
        if message is not None:
            t.message = message
        if commit_sha:
            t.commit_sha = commit_sha

        await self._broadcast(StreamEvent("flush", self._build_payload()))

        # 返回完整 Transcript，清理内部状态
        result = t
        self._transcript = None
        self._sub_streams = []
        self._active = None
        return result

    # ── read (recovery) ──────────────────────────────────

    def get_buffered(self) -> dict[str, str]:
        if self._transcript is None:
            return {}
        parts: list[str] = [s.text for s in self._sub_streams]
        if self._active:
            parts.append(self._active.text)
        return {self._transcript.id: "".join(parts)} if parts else {}

    # ── subscribe ────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue[StreamEvent | None]:
        q: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        self._subscribers.append(q)
        if self._closed:
            q.put_nowait(None)
        return q

    def unsubscribe(self, q: asyncio.Queue[StreamEvent | None]) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    # ── lifecycle ────────────────────────────────────────

    def close(self) -> None:
        self._closed = True
        for q in self._subscribers:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass

    # ── internal ─────────────────────────────────────────

    async def _broadcast(self, event: StreamEvent) -> None:
        dead: list[asyncio.Queue[StreamEvent | None]] = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)
