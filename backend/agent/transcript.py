"""Transcript — 一等存储单元 + 流式构建器。

每个 Transcript 代表会话中一个不可分割的事件。
id 贯穿该事件的整个生命周期（chunk/flush/respond 均以此为 key）。

TranscriptStream 是唯一真相源：
- chunk()  逐步构建 message 内部字段 + 广播 SSE chunk 事件
- flush()  收尾 → 合并 base 字段 → 广播 SSE flush 事件 → 返回 Transcript
- 禁止在 chunk() 之外私自构建 message
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


# ── 存储单元 ──────────────────────────────────────────────


@dataclass
class Transcript:
    """A single event in a session timeline."""

    id: str
    kind: TranscriptKind
    message: dict = field(default_factory=dict)
    commit_sha: str = ""  # non-empty when a shadow commit is attached


# ── 子流（chunk 事件的追踪单元）─────────────────────────────


@dataclass
class SubStream:
    """Transcript 构建过程中的一个子流阶段。

    例如一次 assistant 响应可能依次经历：
      thinking → response → tool_name(tc/0) → tool_arguments(tc/0)
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


# ── chunk kind → message field 映射 ───────────────────────

# 每个 chunk kind 对应 message 中的一个字段路径。
# 对于 tool_name / tool_arguments，索引从 chunk_id 解析（格式 "{tid}/tc/{idx}"）。
_CHUNK_FIELDS: dict[str, str] = {
    "thinking": "reasoning_content",
    "response": "content",
    "tool_result": "result",
}


def _parse_tool_index(chunk_id: str) -> int:
    """从 chunk_id 中提取 tool call 索引，如 'xxx/tc/2' → 2。"""
    if "/tc/" in chunk_id:
        try:
            return int(chunk_id.rsplit("/", 1)[-1])
        except ValueError:
            pass
    return 0


def _ensure_tool_calls(message: dict, idx: int) -> None:
    """确保 message["tool_calls"] 列表至少有 idx+1 项。"""
    calls = message.setdefault("tool_calls", [])
    while len(calls) <= idx:
        calls.append(
            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
        )


# ── 流式构建器 ────────────────────────────────────────────


class TranscriptStream:
    """Per-execution：逐步构建 Transcript 并广播。

    用法:
        stream = TranscriptStream()
        q = stream.subscribe()

        # assistant: 流式输出
        await stream.chunk(tid, "thinking", token)
        await stream.chunk(tid, "response", token)
        t = await stream.flush(tid, "assistant")

        # tool_result: 流式 Shell 输出
        await stream.chunk(rid, "tool_result", chunk_text)
        t = await stream.flush(rid, "tool_result",
            base={"tool_call_id": "tc1", "tool_name": "Shell",
                  "arguments": '{"cmd":"ls"}'})

        # user_question / error: 直接 flush
        t = await stream.flush(uid, "user_question",
            base={"role": "user", "content": "hello"})

        session.add_transcript(t.kind, t.message, t.id)
    """

    def __init__(self) -> None:
        self._transcript: Transcript | None = None
        self._sub_streams: list[SubStream] = []
        self._active: SubStream | None = None
        self._subscribers: list[asyncio.Queue[StreamEvent | None]] = []
        self._closed: bool = False

    # ── read ─────────────────────────────────────────────

    @property
    def message(self) -> dict | None:
        """当前构建中的 message 字典，供调用方直接设置非流式字段
        （如 tool_call id）。若未开始构建则返回 None。"""
        if self._transcript is None:
            return None
        return self._transcript.message

    def ensure_open(self, transcript_id: str, kind: str = "assistant") -> dict:
        """确保 transcript 已初始化，返回 message 字典。

        若尚未构建则自动创建（不发送 chunk 事件）。
        供调用方在首个 chunk 前预置 message 字段（如 tool_call id）。
        """
        if self._transcript is None:
            self._transcript = Transcript(
                id=transcript_id, kind=kind, message={"role": "assistant"}
            )
        return self._transcript.message

    def get_buffered(self) -> dict[str, list[dict]]:
        """返回构建中 transcript 的 sub_stream 快照。

        返回值:  { transcript_id: [ {id, kind, text}, ... ] }
        用于前端重连时回放已输出的流式内容。
        """
        if self._transcript is None:
            return {}
        ss = [{"id": s.id, "kind": s.kind, "text": s.text} for s in self._sub_streams]
        if self._active:
            ss.append(
                {
                    "id": self._active.id,
                    "kind": self._active.kind,
                    "text": self._active.text,
                }
            )
        return {self._transcript.id: ss} if ss else {}

    # ── write ────────────────────────────────────────────

    async def chunk(
        self,
        transcript_id: str,
        kind: str,
        text: str,
        chunk_id: str = "",
    ) -> None:
        """追加文本到 message 的对应字段，并广播 chunk 事件。

        kind → message 字段映射:
          "thinking"       → reasoning_content
          "response"       → content
          "tool_name"      → tool_calls[idx].function.name
          "tool_arguments" → tool_calls[idx].function.arguments
          "tool_result"    → result
        """
        cid = chunk_id or transcript_id

        # 自动初始化 transcript
        if self._transcript is None:
            self._transcript = Transcript(
                id=transcript_id,
                kind="assistant",
                message={"role": "assistant"},
            )

        # ── 更新 message ─────────────────────────
        msg = self._transcript.message
        if kind in ("tool_name", "tool_arguments"):
            idx = _parse_tool_index(cid)
            _ensure_tool_calls(msg, idx)
            if kind == "tool_name":
                msg["tool_calls"][idx]["function"]["name"] += text
            else:
                msg["tool_calls"][idx]["function"]["arguments"] += text
        else:
            field = _CHUNK_FIELDS.get(kind)
            if field:
                msg[field] = msg.get(field, "") + text

        # ── 更新 sub_stream 追踪 ─────────────────
        if self._active and (self._active.id != cid or self._active.kind != kind):
            self._sub_streams.append(self._active)
            self._active = None

        if self._active and self._active.id == cid and self._active.kind == kind:
            self._active.text += text
        else:
            self._active = SubStream(id=cid, kind=kind, text=text)

        # ── 广播 ─────────────────────────────────
        ev = StreamEvent(
            "chunk",
            {
                "transcript_id": transcript_id,
                "id": cid,
                "kind": kind,
                "text": text,
            },
        )
        await self._broadcast(ev)

    async def flush(
        self,
        transcript_id: str,
        kind: str,
        base: dict | None = None,
        commit_sha: str = "",
    ) -> Transcript:
        """收尾当前 Transcript 并广播 flush 事件。

        *base*  非流式字段，与 chunk 累积的字段合并为最终 message。
                调用方负责提供 role、tool_call_id 等。

        返回构建完成的 Transcript。
        """
        if self._transcript is None:
            self._transcript = Transcript(
                id=transcript_id, kind=kind, message=base or {}
            )
        else:
            # base 字段覆盖 chunk 累积值（base 为最终权威来源）
            if base:
                self._transcript.message.update(base)

        t = self._transcript
        t.kind = kind
        if commit_sha:
            t.commit_sha = commit_sha

        # 收尾 active sub_stream
        if self._active:
            self._sub_streams.append(self._active)
            self._active = None

        await self._broadcast(StreamEvent("flush", self._build_payload()))

        result = t
        self._transcript = None
        self._sub_streams = []
        self._active = None
        return result

    # ── helpers ──────────────────────────────────────────

    def _build_payload(self) -> dict[str, Any]:
        t = self._transcript
        if t is None:
            return {}
        ss = self._sub_streams.copy()
        if self._active:
            ss.append(self._active)
        payload: dict[str, Any] = {
            "transcript_id": t.id,
            "kind": t.kind,
            "message": t.message,
            "sub_streams": [{"id": s.id, "kind": s.kind, "text": s.text} for s in ss],
            "active_sub_stream": None,
        }
        if t.commit_sha:
            payload["commit_sha"] = t.commit_sha
        return payload

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
