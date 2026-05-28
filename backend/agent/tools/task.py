"""Task tools — maintain the agent task list."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agent.tools.base import BaseTool
from app.core.config import TMP_DIR

TaskStatus = Literal["pending", "progress", "done"]


def task_context_message(sandbox) -> dict:
    """返回本轮任务列表的系统消息。"""
    try:
        tasks = _load_tasks_for_context(sandbox)
        content = _format_task_context(tasks)
    except Exception as exc:
        content = f"## Current Tasks\nTask context unavailable: {exc}"
    return {"role": "system", "content": content}


async def reconstruct_tasks(sandbox, transcripts: list) -> None:
    """Reconstruct task list by replaying TaskRewrite / TaskUpdate from transcripts.

    Call after transcript truncation (checkout) to restore task state consistency.
    Algorithm:
      1. Scan transcripts backwards for the last successful TaskRewrite.
      2. Execute that TaskRewrite as the base state (or start empty if none).
      3. Replay all TaskUpdate calls after that point (or from the beginning).
    """
    # Step 1: find last TaskRewrite (scan backwards)
    rewrite_index = -1
    for i in range(len(transcripts) - 1, -1, -1):
        t = transcripts[i]
        if t.kind == "assistant":
            for tc in t.message.get("tool_calls", []):
                if tc.get("function", {}).get("name") == "TaskRewrite":
                    rewrite_index = i
                    break
        if rewrite_index >= 0:
            break

    # Step 2: execute the base TaskRewrite (or start empty)
    if rewrite_index >= 0:
        base_t = transcripts[rewrite_index]
        applied = False
        for tc in base_t.message.get("tool_calls", []):
            fn = tc.get("function", {})
            if fn.get("name") == "TaskRewrite":
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                    tool = TaskRewrite(
                        tasks=[Task(**td) for td in args.get("tasks", [])]
                    )
                    await tool.execute(sandbox=sandbox)
                    applied = True
                except Exception:
                    pass
                break
        if not applied:
            await _save_tasks(sandbox, [])
    else:
        await _save_tasks(sandbox, [])

    # Step 3: replay TaskUpdate calls from after the rewrite point
    start = rewrite_index + 1 if rewrite_index >= 0 else 0
    for i in range(start, len(transcripts)):
        t = transcripts[i]
        if t.kind == "assistant":
            for tc in t.message.get("tool_calls", []):
                fn = tc.get("function", {})
                if fn.get("name") == "TaskUpdate":
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                        tool = TaskUpdate(**args)
                        await tool.execute(sandbox=sandbox)
                    except Exception:
                        pass


class Task(BaseModel):
    id: str = Field(..., description="Unique task id.")
    name: str = Field(..., description="Short stable task name.")
    description: str = Field(..., description="Task description.")
    status: TaskStatus = Field(
        ..., description="Task status: pending, progress, or done."
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="Upstream task ids that must be done before this task.",
    )
    summary: str = Field(
        default="",
        description="Task result summary. Required when status is 'done'; MUST be empty for 'pending' or 'progress'.",
    )


class TaskList(BaseTool):
    """Read the current task list."""

    async def execute(self, *, sandbox=None, channel=None, interrupt_event=None, scheduler=None, toolset=None, result_id="") -> str:
        tasks = await _load_tasks(sandbox)
        return _dump({"tasks": _with_blocked(tasks)})


class TaskRewrite(BaseTool):
    """Rewrite the full task list."""

    tasks: list[Task] = Field(
        ...,
        description="The complete task list after rewrite.",
    )

    async def execute(self, *, sandbox=None, channel=None, interrupt_event=None, scheduler=None, toolset=None, result_id="") -> str:
        tasks = [task.model_dump() for task in self.tasks]
        error = _validate_tasks(tasks)
        if error:
            return f"Error: {error}"
        await _save_tasks(sandbox, tasks)
        return "Task list updated."


class TaskUpdate(BaseTool):
    """Update one task status and summary."""

    id: str = Field(..., description="Task id to update.")
    status: TaskStatus = Field(
        ..., description="New task status: pending, progress, or done."
    )
    summary: str = Field(
        ...,
        description="Task summary. Required when status is done; use empty string for pending.",
    )

    async def execute(self, *, sandbox=None, channel=None, interrupt_event=None, scheduler=None, toolset=None, result_id="") -> str:
        tasks = await _load_tasks(sandbox)
        index = _find_task_index(tasks, self.id)
        if index is None:
            return f"Error: task id does not exist: {self.id}"

        current = tasks[index]
        next_task = {
            **current,
            "status": self.status,
            "summary": self.summary,
        }

        next_tasks = [*tasks]
        next_tasks[index] = next_task

        error = _validate_tasks(next_tasks)
        if error:
            return f"Error: {error}"
        if self.status == "done" and not self.summary.strip():
            return "Error: summary is required when marking a task done."
        if self.status in ("progress", "done"):
            unfinished = _unfinished_dependencies(tasks, current)
            if unfinished:
                return (
                    f"Error: cannot mark task {self.status} before dependencies are done: "
                    + ", ".join(unfinished)
                )

        await _save_tasks(sandbox, next_tasks)
        return "Task updated."


def _tasks_path(sandbox) -> Path:
    if sandbox is None:
        raise ValueError("sandbox is required")
    session_id = sandbox.session_id or "default"
    return Path(sandbox.resolve_path(f"{TMP_DIR}/{session_id}/tasks.json"))


def _load_tasks_for_context(sandbox) -> list[dict]:
    path = _tasks_path(sandbox)
    if not path.exists():
        return []
    return _load_tasks_sync(path)


async def _load_tasks(sandbox) -> list[dict]:
    path = _tasks_path(sandbox)
    if not path.exists():
        return []
    return await asyncio.to_thread(_load_tasks_sync, path)


def _load_tasks_sync(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("tasks file must contain a JSON array")
    return data


async def _save_tasks(sandbox, tasks: list[dict]) -> None:
    path = _tasks_path(sandbox)
    await asyncio.to_thread(_save_tasks_sync, path, tasks)


def _save_tasks_sync(path: Path, tasks: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(tasks, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _validate_tasks(tasks: list[dict]) -> str | None:
    ids: set[str] = set()
    for task in tasks:
        task_id = str(task.get("id", ""))
        if not task_id:
            return "task id cannot be empty"
        if task_id in ids:
            return f"duplicate task id: {task_id}"
        ids.add(task_id)
        if task.get("status") not in ("pending", "progress", "done"):
            return f"invalid task status for {task_id}: {task.get('status')}"
        summary = str(task.get("summary", ""))
        if task.get("status") == "done" and not summary.strip():
            return f"task {task_id} is done but summary is empty"
        if task.get("status") in ("pending", "progress") and summary.strip():
            return f"task {task_id} is {task.get('status')} but summary is not empty: {summary}"
        for dep_id in task.get("depends_on", []):
            if dep_id not in ids and dep_id not in {t.get("id") for t in tasks}:
                return f"task {task_id} depends on missing task id: {dep_id}"

    graph = {task["id"]: list(task.get("depends_on", [])) for task in tasks}
    cycle = _find_cycle(graph)
    if cycle:
        return "cycle dependency detected: " + " -> ".join(cycle)
    return None


def _find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(task_id: str) -> list[str] | None:
        if task_id in visiting:
            start = stack.index(task_id)
            return stack[start:] + [task_id]
        if task_id in visited:
            return None

        visiting.add(task_id)
        stack.append(task_id)
        for dep_id in graph.get(task_id, []):
            cycle = visit(dep_id)
            if cycle:
                return cycle
        stack.pop()
        visiting.remove(task_id)
        visited.add(task_id)
        return None

    for task_id in graph:
        cycle = visit(task_id)
        if cycle:
            return cycle
    return None


def _find_task_index(tasks: list[dict], task_id: str) -> int | None:
    for index, task in enumerate(tasks):
        if task.get("id") == task_id:
            return index
    return None


def _format_task_context(tasks: list[dict]) -> str:
    lines = ["## Current Tasks"]

    if not tasks:
        lines.append("No tasks now.")
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


def _unfinished_dependencies(tasks: list[dict], task: dict) -> list[str]:
    by_id = {item["id"]: item for item in tasks}
    return [
        dep_id
        for dep_id in task.get("depends_on", [])
        if by_id.get(dep_id, {}).get("status") != "done"
    ]


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


def _dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
