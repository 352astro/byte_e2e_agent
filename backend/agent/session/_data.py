"""Session — 会话数据容器，Message 的唯一真相源。

每个 Session 持有：
- _messages: list[Message] — Pydantic 消息列表（内存 + 磁盘真相源）
- JSONL 磁盘持久化（Message.model_dump(mode='json')）
- _llm_context: 从 messages 派生的 OpenAI 格式缓存
"""

from __future__ import annotations

import json
import uuid as _uuid
from pathlib import Path

from agent.core.workspace import Workspace, validate_session_id
from agent.tools.toolset import ToolSet
from shared.types import Message, MessageRole


def _default_toolset() -> ToolSet:
    from agent.tools import tool_registry

    return ToolSet(tool_registry)


# ═══════════════════════════════════════════════════════════
# Session
# ═══════════════════════════════════════════════════════════


class Session:
    """一个 agent 会话的完整数据容器。"""

    def __init__(
        self,
        llm_client=None,
        toolset: ToolSet | None = None,
        ws: Workspace | None = None,
        session_id: str | None = None,
    ) -> None:
        self.llm_client = llm_client
        self._toolset = toolset or _default_toolset()
        self._ws = ws or Workspace()
        self.session_id = session_id or _uuid.uuid4().hex[:12]
        self._messages: list[Message] = []
        self._llm_context: list[dict] = []

    # ── Message 管理 ───────────────────────────────────

    def add_message(self, msg: Message) -> None:
        """添加一条已完成 Message，同步持久化到磁盘。"""
        msg.mark_complete()
        self._messages.append(msg)

        # 同步落盘
        _save_message_sync(
            self._ws.root,
            self.session_id,
            msg,
        )

        # 更新 LLM 上下文缓存
        openai_msg = _message_to_openai(msg)
        if openai_msg is not None:
            self._llm_context.append(openai_msg)

    def get_messages(self) -> list[dict]:
        """返回所有 Message 的序列化形式（API / SSE 用）。"""
        return [msg.model_dump(mode="json") for msg in self._messages]

    def get_llm_context(self) -> list[dict]:
        """返回 OpenAI 格式消息列表（供 LLM 调用）。"""
        return [dict(m) for m in self._llm_context]

    # ── 批量操作 ──────────────────────────────────────

    def replace_messages(self, messages: list[Message], persist: bool = False) -> None:
        """替换消息列表并重建 LLM 上下文。"""
        self._messages = messages
        self._llm_context = _build_llm_context(messages)
        if persist:
            _rewrite_messages_file(str(self._ws.root), self.session_id, messages)

    def truncate_by_id(self, msg_id: str, keep: bool = False) -> int:
        """按 message id 截断。keep=False → 删除此 id 及以后；keep=True → 保留此 id。"""
        cutoff = -1
        for i, m in enumerate(self._messages):
            if m.id == msg_id:
                cutoff = i
                break
        if cutoff < 0:
            return 0
        if keep:
            cutoff += 1
        if cutoff >= len(self._messages):
            return 0
        kept = self._messages[:cutoff]
        removed = len(self._messages) - cutoff
        self._messages = kept
        self._llm_context = _build_llm_context(kept)
        _rewrite_messages_file(str(self._ws.root), self.session_id, kept)
        return removed


# ═══════════════════════════════════════════════════════════
# Module API
# ═══════════════════════════════════════════════════════════


def load_session(
    workspace: str | Path,
    session_id: str,
    llm_client=None,
    toolset: ToolSet | None = None,
    ws: Workspace | None = None,
) -> Session:
    """从磁盘 JSONL 重建 Session。"""
    session = Session(
        llm_client=llm_client,
        toolset=toolset,
        ws=ws,
        session_id=session_id,
    )
    messages_path = _messages_path(workspace, session_id)
    if not messages_path.exists():
        return session

    msgs = _load_messages(messages_path)
    if msgs:
        session.replace_messages(msgs, persist=False)
    return session


def get_history(session: Session) -> list[dict]:
    """Return the persisted Message stream for the legacy history endpoint."""
    return session.get_messages()


async def clear(session: Session) -> None:
    session.replace_messages([])


# ═══════════════════════════════════════════════════════════
# Disk persistence
# ═══════════════════════════════════════════════════════════


def _load_messages(messages_path: Path) -> list[Message]:
    """加载 JSONL（仅新 Pydantic Message 格式）。"""
    msgs: list[Message] = []
    with open(messages_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            if "id" in record and "role" in record:
                try:
                    msgs.append(Message.model_validate(record))
                except Exception:
                    pass
    return msgs


def _save_message_sync(
    workspace: str | Path,
    session_id: str,
    msg: Message,
) -> None:
    """追加一条 Message 到 JSONL。"""
    messages_path = _messages_path(workspace, session_id)
    messages_path.parent.mkdir(parents=True, exist_ok=True)
    record = msg.model_dump(mode="json")
    with open(messages_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        fh.write("\n")


def _rewrite_messages_file(
    workspace: str | Path,
    session_id: str,
    messages: list[Message],
) -> None:
    """重写整个 JSONL 文件。"""
    messages_path = _messages_path(workspace, session_id)
    messages_path.parent.mkdir(parents=True, exist_ok=True)
    with open(messages_path, "w", encoding="utf-8") as fh:
        for m in messages:
            record = m.model_dump(mode="json")
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")


# ═══════════════════════════════════════════════════════════
# OpenAI context builders
# ═══════════════════════════════════════════════════════════


def _message_to_openai(msg: Message) -> dict | None:
    """Message → OpenAI chat message dict。"""
    if msg.role == MessageRole.USER:
        return {"role": "user", "content": msg.content}
    if msg.role == MessageRole.ASSISTANT:
        result: dict = {"role": "assistant", "content": msg.content or None}
        if msg.tool_calls:
            result["tool_calls"] = [tc.model_dump(mode="json") for tc in msg.tool_calls]
        if msg.reasoning:
            result["reasoning_content"] = msg.reasoning
        if msg.error:
            result["content"] = msg.error
        return result
    if msg.role == MessageRole.TOOL:
        return {
            "role": "tool",
            "tool_call_id": msg.tool_call_id,
            "content": msg.tool_result or msg.content,
        }
    return None


def _build_llm_context(messages: list[Message]) -> list[dict]:
    """从 Message 列表重建 OpenAI 上下文，过滤孤立的 tool 消息。"""
    result: list[dict] = []
    open_ids: set[str] = set()

    for msg in messages:
        if msg.role == MessageRole.TOOL:
            if msg.tool_call_id not in open_ids:
                continue
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.tool_result,
                }
            )
            open_ids.discard(msg.tool_call_id)
            continue

        openai_msg = _message_to_openai(msg)
        if openai_msg is None:
            continue
        result.append(openai_msg)

        if msg.role == MessageRole.ASSISTANT and msg.tool_calls:
            open_ids = {tc.id for tc in msg.tool_calls}
        else:
            open_ids = set()

    return result


def _safe_json_loads(value: str) -> dict:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


# ═══════════════════════════════════════════════════════════
# Filesystem helpers
# ═══════════════════════════════════════════════════════════


def _messages_path(workspace: str | Path, session_id: str) -> Path:
    return _session_dir(workspace, session_id) / "messages.jsonl"


def _session_dir(workspace: str | Path, session_id: str) -> Path:
    return Workspace(workspace).session_dir(session_id)


def _validate_session_id(session_id: str) -> None:
    validate_session_id(session_id)
