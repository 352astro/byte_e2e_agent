"""Session — 会话数据容器，Transcript 的唯一真相源。

每个 Session 持有：
- _transcripts: 已完成 transcript 的列表（内存真相源）
- JSONL 磁盘持久化（通过 session_memory）
- 从 transcripts 重建 OpenAI 格式消息的能力
"""

from __future__ import annotations

import asyncio
import json
import uuid as _uuid
from typing import Any

import agent.session_memory as session_memory
from agent.llm import HelloAgentsLLM
from agent.sandbox import SandBox
from agent.tools.toolset import ToolSet
from agent.transcript import Transcript, TranscriptKind


def _default_toolset() -> ToolSet:
    from agent.tools import get_all_tool_classes as _all

    return ToolSet(_all())


# ============================================================
# Session
# ============================================================


class Session:
    """一个 agent 会话的完整数据容器。"""

    def __init__(
        self,
        llm_client: HelloAgentsLLM,
        toolset: ToolSet | None = None,
        sandbox: SandBox | None = None,
        session_id: str | None = None,
    ) -> None:
        self.llm_client = llm_client
        self._toolset = toolset or _default_toolset()
        self._sandbox = sandbox or SandBox()
        self.session_id = session_id or self._sandbox.session_id
        self._system_msg: dict | None = None
        self._transcripts: list[Transcript] = []  # 已完成 transcript（唯一真相源）

    # ── transcript 管理 ────────────────────────────────

    def add_transcript(
        self,
        kind: TranscriptKind,
        message: dict,
        transcript_id: str | None = None,
    ) -> Transcript:
        """添加一条已完成 transcript。

        同时触发磁盘持久化（fire-and-forget）。
        返回创建的 Transcript 对象。
        """
        tid = transcript_id or _uuid.uuid4().hex
        t = Transcript(id=tid, kind=kind, message=message)
        self._transcripts.append(t)

        # 磁盘持久化（尽力而为）
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                session_memory.save_transcript(
                    self._sandbox.workspace, self.session_id, kind, tid, message
                )
            )
        except RuntimeError:
            # 没有运行中的 event loop，同步写入
            session_memory._save_transcript_sync(
                self._sandbox.workspace, self.session_id, kind, tid, message
            )
        return t

    def get_transcripts(self) -> list[dict]:
        """返回所有已完成 transcript 的序列化形式。"""
        return [
            {"id": t.id, "kind": t.kind, "message": t.message}
            for t in self._transcripts
        ]

    def get_messages(self) -> list[dict]:
        """从 transcripts 重建 OpenAI 格式消息列表（供 LLM 调用）。"""
        messages: list[dict] = []
        for t in self._transcripts:
            if t.kind == "user_question":
                messages.append(
                    {"role": "user", "content": t.message.get("content", "")}
                )
            elif t.kind == "assistant":
                m: dict = {
                    "role": "assistant",
                    "content": t.message.get("content") or None,
                }
                if t.message.get("tool_calls"):
                    m["tool_calls"] = t.message["tool_calls"]
                if t.message.get("reasoning_content"):
                    m["reasoning_content"] = t.message["reasoning_content"]
                messages.append(m)
            elif t.kind == "tool_result":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": t.message.get("tool_call_id", ""),
                        "content": t.message.get(
                            "result", t.message.get("content", "")
                        ),
                    }
                )
        return messages


# ============================================================
# Public API（兼容旧前端）
# ============================================================


def get_history(session: Session) -> list[dict]:
    """从 transcripts 重建 Turn 兼容格式的历史记录。"""
    result: list[dict] = []

    for t in session._transcripts:
        msg = t.message
        if t.kind == "user_question":
            result.append(
                {
                    "role": "user",
                    "question": msg.get("content", ""),
                    "reasoning": "",
                    "content": "",
                    "tool_calls": [],
                    "finish_answer": None,
                }
            )
        elif t.kind == "assistant":
            tool_calls: list[dict] = []
            for tc in msg.get("tool_calls", []):
                tool_calls.append(
                    {
                        "name": tc["function"]["name"],
                        "arguments": _safe_json_loads(
                            tc["function"].get("arguments", "{}")
                        ),
                        "result": None,
                        "_tc_id": tc.get("id", ""),
                    }
                )
            turn: dict = {
                "role": "assistant",
                "question": "",
                "reasoning": msg.get("reasoning_content", ""),
                "content": msg.get("content") or "",
                "tool_calls": tool_calls,
                "finish_answer": None,
            }
            if not tool_calls and msg.get("content"):
                turn["finish_answer"] = msg["content"]
            result.append(turn)
        elif t.kind == "tool_result":
            tc_id = msg.get("tool_call_id", "")
            for turn in reversed(result):
                if turn["role"] != "assistant":
                    continue
                for tc in turn["tool_calls"]:
                    if tc.get("_tc_id") == tc_id:
                        tc["result"] = msg.get("result", msg.get("content", ""))
                        break
                break

    for turn in result:
        for tc in turn.get("tool_calls", []):
            tc.pop("_tc_id", None)
    return result


async def clear(session: Session) -> None:
    session._system_msg = None
    session._transcripts = []
    await session._sandbox.shutdown()


# ============================================================
# helpers
# ============================================================


def _safe_json_loads(s: str) -> dict:
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {}
