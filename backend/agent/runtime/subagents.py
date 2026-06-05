"""Subagent helpers for AgentRuntime."""

from __future__ import annotations

import json
import uuid as _uuid
from datetime import datetime, timezone

from agent.core.config import SessionConfig, ToolSetPreset
from agent.core.workspace import Workspace
from agent.runtime.context_builder import build_preloaded_skills_context
from agent.session.status import SessionStatus


def build_subagent_preamble(with_skills: list[str]) -> str:
    parts = [
        (
            "You are a sub-agent. Complete the assigned task and return a final "
            "answer. You have an independent session and do not inherit the "
            "parent conversation; rely only on the task and your own tool results."
        )
    ]
    skill_context = build_preloaded_skills_context(with_skills)
    if skill_context:
        parts.append(skill_context)
    return "\n\n".join(parts)


def write_subagent_metadata(
    workspace: Workspace,
    session_id: str,
    *,
    parent_id: str,
    parent_message_id: str,
    parent_tool_call_id: str,
    task: str,
) -> None:
    path = workspace.session_dir(session_id) / "session.json"
    now = datetime.now(timezone.utc).isoformat()
    existing = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    payload = {
        **existing,
        "session_id": session_id,
        "workspace": str(workspace.root),
        "session_kind": "subagent",
        "parent_session_id": parent_id,
        "parent_message_id": parent_message_id,
        "parent_tool_call_id": parent_tool_call_id,
        "task": task,
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


async def invoke_agent(
    runtime,
    caller_id: str,
    target_id: str,
    task: str,
    *,
    max_turns: int | None = None,
    parent_message_id: str = "",
    parent_tool_call_id: str = "",
) -> str:
    resolved = runtime._resolve_id(target_id)
    if resolved is None:
        return f"Error: target session '{target_id}' not found"

    target = runtime._sessions.get(resolved)
    if target is None:
        return f"Error: session '{resolved}' not active"

    if not target.config.access.can_invoke(caller_id):
        return f"Error: session '{resolved}' does not allow invoke from '{caller_id}'"

    caller_entry = runtime._sessions.get(caller_id)
    if caller_entry:
        caller_entry.transition_to(SessionStatus.PENDING)

    created_interrupt_event = False
    if runtime._interrupt_event is None:
        import asyncio

        runtime._interrupt_event = asyncio.Event()
        created_interrupt_event = True
    previous_running = runtime._running_session_id
    try:
        await runtime._hooks.on_subagent_start(
            task=task,
            parent_session_id=caller_id,
            child_session_id=target.id,
            parent_message_id=parent_message_id,
            parent_tool_call_id=parent_tool_call_id,
            max_steps=max_turns or 10,
        )
        runtime._running_session_id = target.id
        target.transition_to(SessionStatus.RUNNING)
        result = await runtime._execute_turn(
            target,
            task,
            max_turns or 10,
            top_level=False,
        )
        runtime._running_session_id = previous_running
        await runtime._hooks.on_subagent_end(
            result=result,
            parent_session_id=caller_id,
            child_session_id=target.id,
            parent_message_id=parent_message_id,
            parent_tool_call_id=parent_tool_call_id,
        )
        return result
    finally:
        runtime._running_session_id = previous_running
        if created_interrupt_event:
            runtime._interrupt_event = None
        if target.status == SessionStatus.RUNNING:
            target.transition_to(SessionStatus.IDLE)
        if caller_entry:
            caller_entry.transition_to(SessionStatus.RUNNING)


async def invoke_subagent(
    runtime,
    caller_id: str,
    task: str,
    *,
    max_steps: int = 5,
    with_skills: list[str] | None = None,
    parent_message_id: str = "",
    parent_tool_call_id: str = "",
) -> str:
    openai_client, model_id = runtime._get_llm()
    child_id = f"{caller_id}-sub-{_uuid.uuid4().hex[:8]}"
    preamble = build_subagent_preamble(with_skills or [])
    child_tools = [
        name
        for name in ToolSetPreset.ALL.tool_names()
        if name not in {"SubAgent", "BrowserInspect", "TaskList", "TaskRewrite"}
    ]
    config = SessionConfig(
        name=f"subagent:{caller_id}",
        model_id=model_id,
        preamble=preamble,
        tool_set_preset=ToolSetPreset.CUSTOM,
        custom_tools=child_tools,
        rules=[task],
        access=SessionConfig.subagent(
            parent_id=caller_id,
            name=f"subagent:{caller_id}",
            task=task,
            model_id=model_id,
        ).access,
    )
    runtime.create_session(
        config,
        session_id=child_id,
        llm_client=openai_client,
        ws=runtime._workspace,
    )
    write_subagent_metadata(
        runtime._workspace,
        child_id,
        parent_id=caller_id,
        parent_message_id=parent_message_id,
        parent_tool_call_id=parent_tool_call_id,
        task=task,
    )
    result = await runtime.invoke_agent(
        caller_id,
        child_id,
        task,
        max_turns=max_steps,
        parent_message_id=parent_message_id,
        parent_tool_call_id=parent_tool_call_id,
    )
    return f"SubAgent session {child_id} completed.\n\n{result}"
