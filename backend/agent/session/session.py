"""SessionTranscript — append-only message transcript and LLM projection.

每个 SessionTranscript 持有：
- _messages: list[Message] — Pydantic 消息列表（内存 + 磁盘真相源）
- JSONL 磁盘持久化（Message.model_dump(mode='json')）
- _llm_context: 从 messages 派生的 OpenAI 格式缓存
"""

from __future__ import annotations

import contextlib
import json
import uuid as _uuid
from pathlib import Path

from agent.core.config import SessionConfig
from agent.core.workspace import Workspace, validate_session_id
from agent.tools.toolset import ToolSet
from shared.types import Message, MessageRole, MessageStatus, ToolCall


def _default_toolset() -> ToolSet:
    from agent.tools import tool_registry

    return ToolSet(tool_registry)


# ═══════════════════════════════════════════════════════════
# SessionTranscript
# ═══════════════════════════════════════════════════════════


class SessionTranscript:
    """Append-only transcript for one agent session."""

    def __init__(
        self,
        workspace: Workspace,
        llm_client=None,
        toolset: ToolSet | None = None,
        session_id: str | None = None,
    ) -> None:
        self.llm_client = llm_client
        self._toolset = toolset or _default_toolset()
        self._workspace = workspace
        self._workspace_uuid = workspace.uuid
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
            self._workspace,
            self.session_id,
            msg,
        )

        # 更新 LLM 上下文缓存。这里重建全量投影，让残缺 tool 序列、
        # interrupted 半截消息等跨消息修复规则始终一致。
        self._llm_context = _build_llm_context(self._messages)

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
            _rewrite_messages_file(self._workspace, self.session_id, messages)

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
        _rewrite_messages_file(self._workspace, self.session_id, kept)
        return removed


# ═══════════════════════════════════════════════════════════
# Module API
# ═══════════════════════════════════════════════════════════


def load_session(
    session_id: str,
    workspace: Workspace | None = None,
    llm_client=None,
    toolset: ToolSet | None = None,
    repair: bool = True,
    persist_repair: bool = True,
) -> SessionTranscript:
    """从磁盘 JSONL 重建 SessionTranscript。"""
    if workspace is None:
        raise ValueError("load_session requires a workspace")
    transcript = SessionTranscript(
        workspace=workspace,
        llm_client=llm_client,
        toolset=toolset,
        session_id=session_id,
    )
    messages_path = _messages_path(workspace, session_id)
    if not messages_path.exists():
        return transcript

    msgs = _load_messages(messages_path)
    if msgs and repair:
        from agent.errors import repair_messages

        msgs = repair_messages(msgs)
    if msgs:
        transcript.replace_messages(msgs, persist=repair and persist_repair)
    return transcript


def get_history(session: SessionTranscript) -> list[dict]:
    """Return the persisted Message stream for the legacy history endpoint."""
    return session.get_messages()


async def clear(session: SessionTranscript) -> None:
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
                with contextlib.suppress(Exception):
                    msgs.append(Message.model_validate(record))
    return msgs


def _save_message_sync(
    workspace: Workspace,
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
    workspace: Workspace,
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


def _system_synthesis(text: str) -> dict:
    return {"role": "system", "content": f"[History repair] {text}"}


def _assistant_synthesis(text: str) -> dict:
    return {"role": "assistant", "content": f"[History repair] {text}"}


def _tool_synthesis(tool_call_id: str, tool_name: str) -> dict:
    label = f" for {tool_name}" if tool_name else ""
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": f"Error: The interrupted tool call{label} did not complete.",
    }


def _valid_tool_call(tc: ToolCall) -> tuple[bool, str]:
    if not tc.id:
        return False, "missing id"
    if tc.type != "function":
        return False, f"unsupported type {tc.type!r}"
    if not tc.function.name:
        return False, "missing function name"
    if not isinstance(tc.function.arguments, str):
        return False, "arguments is not a string"
    try:
        json.loads(tc.function.arguments or "{}")
    except json.JSONDecodeError:
        return False, "arguments is not valid JSON"
    return True, ""


def _assistant_content_for_context(msg: Message) -> str:
    if msg.error:
        return msg.error
    content = msg.content
    if content and msg.status != MessageStatus.COMPLETE:
        return content + "\n\n[History repair] Interrupted before completion."
    return content


def _build_llm_context(messages: list[Message]) -> list[dict]:
    """从 Message 列表重建 OpenAI 上下文。

    原始 Message 历史可以保留 interrupted / streaming 的半截事实；
    这里输出的是给 OpenAI 的合法投影，尽量 synthesis 修复而不是丢弃。
    """
    result: list[dict] = []
    open_ids: set[str] = set()
    open_names: dict[str, str] = {}

    def close_open_tool_calls() -> None:
        nonlocal open_ids, open_names
        for tcid in list(open_ids):
            result.append(_tool_synthesis(tcid, open_names.get(tcid, "")))
        open_ids = set()
        open_names = {}

    for msg in messages:
        if msg.role == MessageRole.SYSTEM:
            result.append({"role": "system", "content": msg.content or ""})
            continue

        if msg.role == MessageRole.TOOL:
            if msg.tool_call_id not in open_ids:
                result.append(
                    _system_synthesis(
                        "Omitted orphaned tool result "
                        f"for tool_call_id={msg.tool_call_id or '<missing>'}."
                    )
                )
                continue
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.tool_result
                    or msg.content
                    or "[History repair] Tool returned no content.",
                }
            )
            open_ids.discard(msg.tool_call_id)
            open_names.pop(msg.tool_call_id, None)
            continue

        if open_ids:
            close_open_tool_calls()

        if msg.role == MessageRole.USER:
            result.append(
                {
                    "role": "user",
                    "content": msg.content or "[History repair] Empty user message.",
                }
            )
            continue

        if msg.role != MessageRole.ASSISTANT:
            continue

        valid_tool_calls: list[ToolCall] = []
        invalid_tool_notes: list[str] = []
        for idx, tc in enumerate(msg.tool_calls):
            valid, reason = _valid_tool_call(tc)
            if valid:
                valid_tool_calls.append(tc)
            else:
                name = tc.function.name or "<unknown>"
                invalid_tool_notes.append(f"#{idx + 1} {name}: {reason}")

        if invalid_tool_notes:
            result.append(
                _system_synthesis(
                    "Omitted malformed assistant tool call(s): "
                    + "; ".join(invalid_tool_notes)[:600]
                )
            )

        content = _assistant_content_for_context(msg)
        if valid_tool_calls:
            openai_msg: dict = {
                "role": "assistant",
                "content": content or None,
                "tool_calls": [tc.model_dump(mode="json") for tc in valid_tool_calls],
            }
            result.append(openai_msg)
            open_ids = {tc.id for tc in valid_tool_calls}
            open_names = {tc.id: tc.function.name for tc in valid_tool_calls}
            continue

        if content:
            result.append({"role": "assistant", "content": content})
        elif msg.reasoning:
            result.append(
                _assistant_synthesis(
                    "Interrupted during reasoning before producing visible output."
                )
            )
        else:
            result.append(_assistant_synthesis("Interrupted before producing visible output."))

    if open_ids:
        close_open_tool_calls()

    return result


def _safe_json_loads(value: str) -> dict:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


# ═══════════════════════════════════════════════════════════
# Filesystem helpers
# ═══════════════════════════════════════════════════════════


def _messages_path(workspace: Workspace, session_id: str) -> Path:
    return _session_dir(workspace, session_id) / "messages.jsonl"


def _session_dir(workspace: Workspace, session_id: str) -> Path:
    from agent.paths import session_dir as _sdir

    return _sdir(workspace.uuid, session_id)


def _validate_session_id(session_id: str) -> None:
    validate_session_id(session_id)


# ═══════════════════════════════════════════════════════════
# Session immutable prefix — written once at session creation
# ═══════════════════════════════════════════════════════════


def write_session_prefix(
    workspace: Workspace | None = None,
    session_id: str = "",
    config: SessionConfig | None = None,
) -> None:
    """Write the immutable prefix messages to a new session's JSONL.

    These messages form the KV-cache anchor — they never change across
    the session's lifetime. Called once from AgentRuntime.create_session().
    """
    import uuid as _uuid

    from agent.core.prompts import SYSTEM_PROMPT
    from agent.tools.shell import get_platform_hint
    from agent.tools.skill import get_skill, skill_context_message

    if workspace is None or config is None:
        raise ValueError("write_session_prefix requires workspace and config")

    turn_id = _uuid.uuid4().hex

    prefix_messages: list[Message] = [
        Message.system_message(_uuid.uuid4().hex, turn_id, SYSTEM_PROMPT),
        Message.system_message(
            _uuid.uuid4().hex,
            turn_id,
            f"## Platform\n{get_platform_hint()}",
        ),
        Message.system_message(_uuid.uuid4().hex, turn_id, skill_context_message()["content"]),
    ]

    if config.preloaded_skills:
        parts: list[str] = []
        for skill_name in config.preloaded_skills:
            skill = get_skill(skill_name)
            if skill is None:
                continue
            parts.append(
                f"[SKILL: {skill_name}]\n\n"
                "The following skill methodology is pre-loaded into your context. "
                "Follow it exactly.\n\n"
                f"{skill.read()}"
            )
        if parts:
            prefix_messages.append(
                Message.system_message(_uuid.uuid4().hex, turn_id, "\n\n".join(parts))
            )

    if config.preamble:
        prefix_messages.append(Message.system_message(_uuid.uuid4().hex, turn_id, config.preamble))

    if config.assigned_task:
        prefix_messages.append(
            Message.system_message(
                _uuid.uuid4().hex,
                turn_id,
                "## Assigned Task\n" + config.assigned_task,
            )
        )

    if config.rules:
        prefix_messages.append(
            Message.system_message(
                _uuid.uuid4().hex,
                turn_id,
                "## Session Rules\n" + "\n".join(f"- {rule}" for rule in config.rules),
            )
        )

    for msg in prefix_messages:
        _save_message_sync(workspace, session_id, msg)
