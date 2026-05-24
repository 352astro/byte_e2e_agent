"""Session — 会话数据容器，Transcript 的唯一真相源。

每个 Session 持有：
- _transcripts: 已完成 transcript 的列表（内存真相源）
- JSONL 磁盘持久化
- _messages: 从 transcripts 派生的 OpenAI 格式消息缓存
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid as _uuid
from pathlib import Path

from agent.llm import HelloAgentsLLM
from agent.sandbox import SandBox
from agent.tools.toolset import ToolSet
from agent.transcript import Transcript, TranscriptKind

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


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
        self._transcripts: list[Transcript] = []  # 已完成 transcript（唯一真相源）
        self._messages: list[dict] = []  # LLM 调用消息缓存

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
        llm_message = self._transcript_to_message(t)
        if llm_message is not None:
            self._messages.append(llm_message)

        # 磁盘持久化（尽力而为）
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                save_transcript(
                    self._sandbox.workspace, self.session_id, kind, tid, message
                )
            )
        except RuntimeError:
            # 没有运行中的 event loop，同步写入
            _save_transcript_sync(
                self._sandbox.workspace, self.session_id, kind, tid, message
            )
        return t

    def get_transcripts(self) -> list[dict]:
        """返回所有已完成 transcript 的序列化形式。"""
        return [
            {"id": t.id, "kind": t.kind, "message": t.message}
            for t in self._transcripts
        ]

    def replace_transcripts(self, transcripts: list[Transcript]) -> None:
        """替换 transcript 列表，并同步重建 LLM 消息缓存。"""
        self._transcripts = list(transcripts)
        self._messages = []
        for t in self._transcripts:
            llm_message = self._transcript_to_message(t)
            if llm_message is not None:
                self._messages.append(llm_message)

    def get_messages(self) -> list[dict]:
        """返回缓存的 OpenAI 格式消息列表（供 LLM 调用）。"""
        return [dict(message) for message in self._messages]

    def _transcript_to_message(self, transcript: Transcript) -> dict | None:
        """把一个 transcript 转换成 LLM 消息；非对话事件返回 None。"""
        message = transcript.message
        if transcript.kind == "user_question":
            return {"role": "user", "content": message.get("content", "")}
        if transcript.kind == "assistant":
            result: dict = {
                "role": "assistant",
                "content": message.get("content") or None,
            }
            if message.get("tool_calls"):
                result["tool_calls"] = message["tool_calls"]
            if message.get("reasoning_content"):
                result["reasoning_content"] = message["reasoning_content"]
            return result
        if transcript.kind == "tool_result":
            return {
                "role": "tool",
                "tool_call_id": message.get("tool_call_id", ""),
                "content": message.get("result", message.get("content", "")),
            }
        return None


# ============================================================
# Public API（兼容旧前端）
# ============================================================


def load_session(
    workspace: str | Path,
    session_id: str,
    llm_client: HelloAgentsLLM,
    toolset: ToolSet | None = None,
    sandbox: SandBox | None = None,
) -> Session:
    """从持久化 transcripts 重建 Session，并同步 LLM 消息缓存。"""
    session = Session(
        llm_client=llm_client,
        toolset=toolset,
        sandbox=sandbox,
        session_id=session_id,
    )

    messages_path = _messages_path(workspace, session_id)
    if not messages_path.exists():
        return session

    transcripts: list[Transcript] = []
    with open(messages_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and "uuid" in record and "kind" in record:
                transcripts.append(
                    Transcript(
                        id=record["uuid"],
                        kind=record["kind"],
                        message=record.get("message", {}),
                    )
                )
            elif isinstance(record, dict) and "role" in record:
                role = record.get("role", "")
                kind = {
                    "user": "user_question",
                    "assistant": "assistant",
                    "tool": "tool_result",
                }.get(role, "assistant")
                transcripts.append(
                    Transcript(
                        id=_uuid.uuid4().hex,
                        kind=kind,
                        message=record,
                    )
                )

    session.replace_transcripts(transcripts)
    return session


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
    session.replace_transcripts([])
    await session._sandbox.shutdown()


# ============================================================
# helpers
# ============================================================


def _safe_json_loads(s: str) -> dict:
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {}


async def save_transcript(
    workspace: str | Path,
    session_id: str,
    kind: TranscriptKind,
    transcript_uuid: str,
    message: dict,
) -> None:
    """追加保存一条 transcript 到当前 session 的 JSONL 文件。"""
    await asyncio.to_thread(
        _save_transcript_sync, workspace, session_id, kind, transcript_uuid, message
    )


def _save_transcript_sync(
    workspace: str | Path,
    session_id: str,
    kind: TranscriptKind,
    transcript_uuid: str,
    message: dict,
) -> None:
    messages_path = _messages_path(workspace, session_id)
    messages_path.parent.mkdir(parents=True, exist_ok=True)
    record = {"kind": kind, "uuid": transcript_uuid, "message": message}
    with open(messages_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        fh.write("\n")


def _messages_path(workspace: str | Path, session_id: str) -> Path:
    return _session_dir(workspace, session_id) / "messages.jsonl"


def _session_dir(workspace: str | Path, session_id: str) -> Path:
    _validate_session_id(session_id)
    return Path(workspace).expanduser().resolve() / ".tmp" / session_id


def _validate_session_id(session_id: str) -> None:
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError(f"Invalid session_id: {session_id!r}")
