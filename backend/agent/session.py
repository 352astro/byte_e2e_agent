"""Session — 会话数据容器，Transcript 的唯一真相源。

每个 Session 持有：
- _transcripts: 已完成 transcript 的列表（内存真相源）
- JSONL 磁盘持久化
- _messages: 从 transcripts 派生的 OpenAI 格式消息缓存
"""

from __future__ import annotations

import json
import re
import uuid as _uuid
from collections.abc import Callable
from pathlib import Path

from agent.llm import HelloAgentsLLM
from agent.sandbox import SandBox
from agent.tools.toolset import ToolSet
from agent.transcript import Transcript, TranscriptKind
from app.core.config import TMP_DIR

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
MessageConverter = Callable[[Transcript], dict | None]
_LEGACY_ROLE_TO_KIND: dict[str, TranscriptKind] = {
    "user": "user_question",
    "assistant": "assistant",
    "tool": "tool_result",
}


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
        commit_sha: str = "",
    ) -> Transcript:
        """添加一条已完成 transcript。

        同时触发磁盘持久化。
        返回创建的 Transcript 对象。
        """
        tid = transcript_id or _uuid.uuid4().hex
        t = Transcript(id=tid, kind=kind, message=message, commit_sha=commit_sha)
        self._transcripts.append(t)
        llm_message = self._transcript_to_message(t)
        if llm_message is not None:
            self._messages.append(llm_message)

        # 必须同步写入以保持 assistant tool_calls -> tool_result 的落盘顺序。
        # fire-and-forget 任务可能乱序完成，重启后会形成孤立 tool message。
        _save_transcript_sync(
            self._sandbox.workspace,
            self.session_id,
            kind,
            tid,
            message,
            commit_sha,
        )
        return t

    def get_transcripts(self) -> list[dict]:
        """返回所有已完成 transcript 的序列化形式。"""
        return [
            {"id": t.id, "kind": t.kind, "message": t.message, "commit_sha": t.commit_sha}
            for t in self._transcripts
        ]

    def replace_transcripts(self, transcripts: list[Transcript]) -> None:
        """替换 transcript 列表，并同步重建 LLM 消息缓存。"""
        self._transcripts = _normalize_transcript_order(transcripts)
        self._messages = _build_llm_messages(
            self._transcripts, self._transcript_to_message
        )

    def truncate_transcripts_from(self, commit_sha: str) -> int:
        """删除匹配 commit_sha 的 transcript 及其后所有 transcript。

        同步重写磁盘 JSONL 文件。
        返回被删除的数量。
        """
        cutoff = -1
        for i, t in enumerate(self._transcripts):
            if t.commit_sha == commit_sha:
                cutoff = i
                break
        if cutoff < 0:
            return 0

        # Keep only transcripts before the cutoff
        kept = self._transcripts[:cutoff]
        removed_count = len(self._transcripts) - cutoff
        self._transcripts = kept
        self._messages = _build_llm_messages(kept, self._transcript_to_message)

        # Rewrite disk file
        _rewrite_messages_file(
            self._sandbox.workspace,
            self.session_id,
            kept,
        )
        return removed_count

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
# Module API（供 app/services/project.py 调用）
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

    session.replace_transcripts(_load_transcripts(messages_path))
    # Repair any unpaired tool_calls from interrupted sessions
    from agent.interrupt import repair_unpaired_tools
    repair_unpaired_tools(session)
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
            result.append(_assistant_history_turn(msg))
        elif t.kind == "tool_result":
            _attach_tool_result(result, msg)

    for turn in result:
        for tc in turn.get("tool_calls", []):
            tc.pop("_tc_id", None)
    return result


async def clear(session: Session) -> None:
    session.replace_transcripts([])
    await session._sandbox.shutdown()


# ============================================================
# Transcript loading / persistence
# ============================================================


def _load_transcripts(messages_path: Path) -> list[Transcript]:
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

            transcript = _record_to_transcript(record)
            if transcript is not None:
                transcripts.append(transcript)
    return transcripts


def _record_to_transcript(record: object) -> Transcript | None:
    """读取当前 JSONL 格式，并兼容早期直接落 OpenAI message 的格式。"""
    if not isinstance(record, dict):
        return None

    if "uuid" in record and "kind" in record:
        return Transcript(
            id=record["uuid"],
            kind=record["kind"],
            message=record.get("message", {}),
            commit_sha=record.get("commit_sha", ""),
        )

    if "role" in record:
        role = record.get("role", "")
        return Transcript(
            id=_uuid.uuid4().hex,
            kind=_LEGACY_ROLE_TO_KIND.get(role, "assistant"),
            message=record,
        )

    return None


def _rewrite_messages_file(
    workspace: str | Path,
    session_id: str,
    transcripts: list[Transcript],
) -> None:
    """Rewrite the entire JSONL file with the given transcripts."""
    messages_path = _messages_path(workspace, session_id)
    messages_path.parent.mkdir(parents=True, exist_ok=True)
    with open(messages_path, "w", encoding="utf-8") as fh:
        for t in transcripts:
            record = {"kind": t.kind, "uuid": t.id, "message": t.message}
            if t.commit_sha:
                record["commit_sha"] = t.commit_sha
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")


def _save_transcript_sync(
    workspace: str | Path,
    session_id: str,
    kind: TranscriptKind,
    transcript_uuid: str,
    message: dict,
    commit_sha: str = "",
) -> None:
    messages_path = _messages_path(workspace, session_id)
    messages_path.parent.mkdir(parents=True, exist_ok=True)
    record = {"kind": kind, "uuid": transcript_uuid, "message": message}
    if commit_sha:
        record["commit_sha"] = commit_sha
    with open(messages_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        fh.write("\n")


# ============================================================
# Transcript repair / LLM message cache
# ============================================================


def _normalize_transcript_order(transcripts: list[Transcript]) -> list[Transcript]:
    """Repair persisted transcripts where tool_result arrived before tool_calls."""
    result: list[Transcript] = []
    pending_tools: dict[str, list[Transcript]] = {}

    for transcript in transcripts:
        if transcript.kind == "tool_result":
            tool_call_id = transcript.message.get("tool_call_id", "")
            if _has_open_tool_call(result, tool_call_id):
                result.append(transcript)
            else:
                pending_tools.setdefault(tool_call_id, []).append(transcript)
            continue

        result.append(transcript)

        if transcript.kind != "assistant":
            continue
        for tc in transcript.message.get("tool_calls", []) or []:
            tool_call_id = tc.get("id", "")
            for pending in pending_tools.pop(tool_call_id, []):
                result.append(pending)

    for pending in pending_tools.values():
        result.extend(pending)
    return result


def _has_open_tool_call(transcripts: list[Transcript], tool_call_id: str) -> bool:
    if not tool_call_id:
        return False
    answered: set[str] = set()
    for transcript in reversed(transcripts):
        if transcript.kind == "tool_result":
            answered.add(transcript.message.get("tool_call_id", ""))
            continue
        if transcript.kind != "assistant":
            continue
        call_ids = {
            tc.get("id", "")
            for tc in transcript.message.get("tool_calls", []) or []
        }
        return tool_call_id in call_ids and tool_call_id not in answered
    return False


def _build_llm_messages(
    transcripts: list[Transcript],
    convert: MessageConverter,
) -> list[dict]:
    """重建 OpenAI messages；跳过没有对应 assistant tool_calls 的 tool 结果。"""
    messages: list[dict] = []
    open_tool_call_ids: set[str] = set()

    for transcript in transcripts:
        llm_message = convert(transcript)
        if llm_message is None:
            continue

        if llm_message.get("role") == "tool":
            tool_call_id = llm_message.get("tool_call_id", "")
            if tool_call_id not in open_tool_call_ids:
                continue
            messages.append(llm_message)
            open_tool_call_ids.discard(tool_call_id)
            continue

        messages.append(llm_message)
        if llm_message.get("role") == "assistant" and llm_message.get("tool_calls"):
            open_tool_call_ids = {
                tc.get("id", "") for tc in llm_message.get("tool_calls", [])
            }
        else:
            open_tool_call_ids = set()

    return messages


# ============================================================
# History compatibility helpers
# ============================================================


def _assistant_history_turn(message: dict) -> dict:
    tool_calls = [_history_tool_call(tc) for tc in message.get("tool_calls", [])]
    turn: dict = {
        "role": "assistant",
        "question": "",
        "reasoning": message.get("reasoning_content", ""),
        "content": message.get("content") or "",
        "tool_calls": tool_calls,
        "finish_answer": None,
    }
    if not tool_calls and message.get("content"):
        turn["finish_answer"] = message["content"]
    return turn


def _history_tool_call(tool_call: dict) -> dict:
    function = tool_call["function"]
    return {
        "name": function["name"],
        "arguments": _safe_json_loads(function.get("arguments", "{}")),
        "result": None,
        "_tc_id": tool_call.get("id", ""),
    }


def _attach_tool_result(history: list[dict], message: dict) -> None:
    tool_call_id = message.get("tool_call_id", "")
    for turn in reversed(history):
        if turn["role"] != "assistant":
            continue
        for tool_call in turn["tool_calls"]:
            if tool_call.get("_tc_id") == tool_call_id:
                tool_call["result"] = message.get(
                    "result",
                    message.get("content", ""),
                )
                break
        break


def _safe_json_loads(value: str) -> dict:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


# ============================================================
# Filesystem helpers
# ============================================================


def _messages_path(workspace: str | Path, session_id: str) -> Path:
    return _session_dir(workspace, session_id) / "messages.jsonl"


def _session_dir(workspace: str | Path, session_id: str) -> Path:
    _validate_session_id(session_id)
    return Path(workspace).expanduser().resolve() / TMP_DIR / session_id


def _validate_session_id(session_id: str) -> None:
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError(f"Invalid session_id: {session_id!r}")
