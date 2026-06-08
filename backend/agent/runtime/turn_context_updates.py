"""Append-only turn context update planning."""

from __future__ import annotations

from dataclasses import dataclass

from agent.runtime.llm_context_builder import build_llm_messages


@dataclass(frozen=True)
class ContextUpdate:
    kind: str
    content: str


def _context_update(kind: str, body: str) -> str:
    return (
        f"## Context Update: {kind}\n"
        "This is supporting context for the immediately preceding user request. "
        "It does not replace or override that request.\n\n"
        f"{body.strip()}"
    )


def _find_last_context_update(history: list[dict], kind: str) -> str:
    prefix = f"## Context Update: {kind}"
    legacy_prefixes = {
        "Available Skills": "## Available Skills",
        "Long-term Memory": "## Long-term Memory",
    }
    for message in reversed(history):
        if message.get("role") != "system":
            continue
        content = message.get("content", "")
        if content.startswith(prefix):
            return content
        legacy = legacy_prefixes.get(kind)
        if legacy and content.startswith(legacy):
            return content
    return ""


def _kind_for_hook_context(content: str) -> str:
    if content.startswith("## Long-term Memory"):
        return "Long-term Memory"
    return "Runtime Context"


def plan_skills_update(history: list[dict]) -> ContextUpdate | None:
    from agent.tools.skill import skill_context_message

    body = skill_context_message()["content"]
    current = _context_update("Available Skills", body)
    previous = _find_last_context_update(history, "Available Skills")
    if previous in (current, body):
        return None
    return ContextUpdate(kind="Available Skills", content=current)


async def plan_hook_context_updates(
    hooks,
    *,
    turn_id: str,
    session_id: str,
    user_question: str,
    history: list[dict],
) -> list[ContextUpdate]:
    updates: list[ContextUpdate] = []
    seen: set[tuple[str, str]] = set()
    injected = await hooks.gather_context(
        turn_id=turn_id,
        session_id=session_id,
        user_question=user_question,
    )
    for item in injected:
        if item.get("role") != "system" or not item.get("content"):
            continue
        body = item["content"]
        kind = _kind_for_hook_context(body)
        content = _context_update(kind, body)
        marker = (kind, content)
        if marker in seen:
            continue
        previous = _find_last_context_update(history, kind)
        if previous in (content, body):
            continue
        seen.add(marker)
        updates.append(ContextUpdate(kind=kind, content=content))
    return updates


def count_turns_since_last_task_tool(history: list[dict]) -> int:
    turns = 0
    for message in reversed(history):
        role = message.get("role", "")
        if role == "user":
            turns += 1
            continue
        if role != "assistant":
            continue
        for tool_call in message.get("tool_calls") or []:
            name = (tool_call.get("function") or {}).get("name", "")
            if name in ("TaskList", "TaskRewrite", "TaskUpdate"):
                return turns
    return turns


def tasks_exist(workspace, session_id: str) -> bool:
    try:
        from agent.tools.task import _load_tasks_sync, _tasks_path

        path = _tasks_path(workspace, session_id)
        if not path.exists():
            return False
        return bool(_load_tasks_sync(path))
    except Exception:
        return False


_TASK_STALE_THRESHOLD = 2
_TASK_REMINDER_BODY = (
    "A task list exists for this session. If it is relevant to the current work, "
    "use TaskList to review current status before continuing."
)


def plan_task_update(
    history: list[dict], *, workspace, session_id: str
) -> ContextUpdate | None:
    if count_turns_since_last_task_tool(history) < _TASK_STALE_THRESHOLD:
        return None
    if not tasks_exist(workspace, session_id):
        return None
    content = _context_update("Task State", _TASK_REMINDER_BODY)
    if content == _find_last_context_update(history, "Task State"):
        return None
    return ContextUpdate(kind="Task State", content=content)


async def plan_context_updates(
    *,
    hooks,
    session_id: str,
    turn_id: str,
    workspace,
    user_question: str,
) -> list[ContextUpdate]:
    history = build_llm_messages(session_id=session_id, workspace=workspace)
    updates: list[ContextUpdate] = []
    skills = plan_skills_update(history)
    if skills:
        updates.append(skills)
        history = [*history, {"role": "system", "content": skills.content}]
    memory_updates = await plan_hook_context_updates(
        hooks,
        turn_id=turn_id,
        session_id=session_id,
        user_question=user_question,
        history=history,
    )
    updates.extend(memory_updates)
    history.extend({"role": "system", "content": update.content} for update in memory_updates)
    task_update = plan_task_update(history, workspace=workspace, session_id=session_id)
    if task_update:
        updates.append(task_update)
    return updates
