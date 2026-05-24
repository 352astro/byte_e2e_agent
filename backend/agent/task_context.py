"""Build runtime task context messages for the agent loop."""

from __future__ import annotations

import json
from pathlib import Path


def task_context_message(sandbox) -> dict:
    """Return a transient message with the current task list."""
    try:
        tasks = load_tasks(sandbox)
        content = format_task_context(tasks)
    except Exception as exc:
        content = f"## Current Tasks\nTask context unavailable: {exc}"
    return {"role": "user", "content": content}


def load_tasks(sandbox) -> list[dict]:
    """Load the current session task list."""
    path = tasks_path(sandbox)
    if not path.exists():
        return []

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("tasks file must contain a JSON array")
    return data


def tasks_path(sandbox) -> Path:
    """Return the current session task file path."""
    if sandbox is None:
        raise ValueError("sandbox is required")
    session_id = sandbox.session_id or "default"
    return Path(sandbox.resolve_path(f".tmp/{session_id}/tasks.json"))


def format_task_context(tasks: list[dict]) -> str:
    """Format tasks as a compact prompt context."""
    lines = [
        "## Current Tasks",
    ]

    if not tasks:
        lines.append(
            "No tasks now."
        )
        return "\n".join(lines)

    for task in _with_blocked(tasks):
        status = "blocked" if task["blocked"] else task.get("status", "pending")
        title = task.get("name") or task.get("description", "")
        lines.append(f"- [{status}] {task.get('id')}: {title}")

        depends_on = task.get("depends_on") or []
        if depends_on:
            lines.append(f"  depends_on: {depends_on}")

        description = task.get("description", "")
        if description and description != title:
            lines.append(f"  description: {description}")

        summary = task.get("summary", "")
        if summary:
            lines.append(f"  summary: {summary}")

    return "\n".join(lines)


def _with_blocked(tasks: list[dict]) -> list[dict]:
    result: list[dict] = []
    for task in tasks:
        result.append(
            {
                **task,
                "blocked": task.get("status") == "pending"
                and bool(_unfinished_dependencies(tasks, task)),
            }
        )
    return result


def _unfinished_dependencies(tasks: list[dict], task: dict) -> list[str]:
    by_id = {item.get("id"): item for item in tasks}
    return [
        dep_id
        for dep_id in task.get("depends_on", [])
        if by_id.get(dep_id, {}).get("status") != "done"
    ]
