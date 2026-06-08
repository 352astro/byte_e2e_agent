"""Subagent helpers for AgentRuntime."""

from __future__ import annotations

import json
import uuid as _uuid
from datetime import UTC, datetime

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
    now = datetime.now(UTC).isoformat()
    existing = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError, OSError:
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

    parent_run = runtime._runs.get(caller_id)
    interrupt_event = (
        parent_run.interrupt_event if parent_run is not None else runtime._interrupt_event
    )
    try:
        await runtime._hooks.on_subagent_start(
            task=task,
            parent_session_id=caller_id,
            child_session_id=target.id,
            parent_message_id=parent_message_id,
            parent_tool_call_id=parent_tool_call_id,
            max_steps=max_turns or 10,
        )
        runtime._begin_run(target, interrupt_event=interrupt_event)
        result = await runtime._execute_turn(
            target,
            task,
            max_turns or 10,
            top_level=False,
        )
        await runtime._hooks.on_subagent_end(
            result=result,
            parent_session_id=caller_id,
            child_session_id=target.id,
            parent_message_id=parent_message_id,
            parent_tool_call_id=parent_tool_call_id,
        )
        return result
    finally:
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


async def invoke_browser_inspect(
    runtime,
    caller_id: str,
    *,
    url: str,
    prompt: str,
    max_steps: int = 8,
    parent_message_id: str = "",
    parent_tool_call_id: str = "",
) -> str:
    openai_client, model_id = runtime._get_llm()
    child_id = f"{caller_id}-browser-{_uuid.uuid4().hex[:8]}"
    config = SessionConfig(
        name=f"browser:{caller_id}",
        model_id=model_id,
        preamble=(
            "You are a browser inspection sub-agent. Your toolset contains "
            "ONLY BrowserObserve and BrowserAct. The page is already open inside "
            "a BrowserGym environment. BrowserObserve reads the current page as "
            "a rich text observation with actionable elements, page outline, bbox, "
            "and visibility data; it never opens URLs. BrowserAct takes a "
            "structured action with a primitive such as click, fill, "
            "keyboard_press, scroll, or goto. Prefer bid over CSS selectors for "
            "element actions. Inspect the current page and report what you see. "
            "Keep your reasoning extremely brief."
        ),
        tool_set_preset=ToolSetPreset.CUSTOM,
        custom_tools=["BrowserObserve", "BrowserAct"],
        rules=[prompt],
        access=SessionConfig.subagent(
            parent_id=caller_id,
            name=f"browser:{caller_id}",
            task=prompt,
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
        task=prompt,
    )

    from agent.tools.browser import close_browser_session, start_browsergym_session

    try:
        open_result = await start_browsergym_session(
            child_id,
            url=url,
            goal=prompt,
            max_bytes=20_000,
        )
        task = (
            f"{prompt}\n\n"
            f"The page has already been opened at: {url}\n"
            "Use BrowserObserve with detail='full' whenever you need to inspect "
            "the current page again. Use the bid values from BrowserObserve and "
            "the initial BrowserGym observation below. Use BrowserAct with "
            "structured actions, for example "
            "{primitive: 'click', bid: '12'}, "
            "{primitive: 'fill', bid: '23', text: 'hello'}, "
            "{primitive: 'keyboard_press', key: 'Enter'}, "
            "{primitive: 'scroll', dy: 600}, or "
            "{primitive: 'goto', url: 'http://...'}."
            "\n\nInitial page state:\n"
            f"{open_result}"
        )
        result = await runtime.invoke_agent(
            caller_id,
            child_id,
            task,
            max_turns=max_steps,
            parent_message_id=parent_message_id,
            parent_tool_call_id=parent_tool_call_id,
        )
        return f"BrowserInspect session {child_id} completed.\n\n{result}"
    finally:
        await close_browser_session(child_id)


# ═══════════════════════════════════════════════════════════
# run_subagent — standalone subagent loop (moved from actions.py)
# ═══════════════════════════════════════════════════════════


async def run_subagent(
    ws,
    toolset,
    prompt: str,
    max_steps: int,
    *,
    openai_client=None,
    model_id: str = "",
    session_id: str,
    interrupt_event,
    with_skills: list[str] | None = None,
    system_extra: str | None = None,
    hook_manager=None,
    human_input_requester=None,
) -> str:
    """Run a sub-agent within the same session from a blank context."""
    import uuid as _uuid

    from agent.llm_call import model_call
    from agent.tool_execution import execute_one_tool
    from agent.tools.skill import get_skill

    subagent_tools = toolset.without(
        "SubAgent", "BrowserInspect", "TaskList", "TaskRewrite"
    ).openai_tools

    subagent_messages: list[dict] = [
        {
            "role": "system",
            "content": (
                "You are a sub-agent. Complete the assigned task and return a final answer."
            ),
        },
    ]

    if with_skills:
        for skill_name in with_skills:
            skill = get_skill(skill_name)
            if skill is not None:
                subagent_messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"[SKILL: {skill_name}]\n\n"
                            f"The following skill methodology is pre-loaded "
                            f"into your context. Follow it exactly.\n\n"
                            f"{skill.read()}"
                        ),
                    }
                )

    if system_extra:
        subagent_messages.append({"role": "system", "content": system_extra})

    subagent_messages.append({"role": "user", "content": prompt})

    last_answer = ""

    for _ in range(max_steps):
        if interrupt_event.is_set():
            break

        stream_id = _uuid.uuid4().hex

        msg, finish_reason = await model_call(
            openai_client,
            model_id,
            session_id,
            subagent_messages,
            subagent_tools,
            message_id=stream_id,
            turn_id=stream_id,
            interrupt_event=interrupt_event,
            hook_manager=hook_manager,
        )

        content = msg.content
        tool_calls = [tc.model_dump() for tc in msg.tool_calls] if msg.tool_calls else []

        if content:
            last_answer = content

        if finish_reason == "stop" or not tool_calls:
            break

        subagent_messages.append(
            {
                "role": "assistant",
                "content": content or None,
                "tool_calls": tool_calls,
                **({"reasoning_content": msg.reasoning} if msg.reasoning else {}),
            }
        )

        for tc in tool_calls:
            if interrupt_event.is_set():
                break
            result = await execute_one_tool(
                tc,
                ws,
                toolset,
                interrupt_event=interrupt_event,
                openai_client=openai_client,
                model_id=model_id,
                session_id=session_id,
                hook_manager=hook_manager,
                human_input_requester=human_input_requester,
            )
            subagent_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result.output,
                }
            )

    return (
        f"SubAgent completed. Result: {last_answer}"
        if last_answer
        else "SubAgent completed (no output)."
    )
