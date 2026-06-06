"""Turn execution driver for AgentRuntime."""

from __future__ import annotations

import logging
import uuid as _uuid

from agent.actions import model_call
from agent.errors import InterruptedError
from agent.runtime.context_builder import build_llm_messages
from agent.runtime.messages import emit_system_message, extract_usage
from agent.runtime.tooling import default_toolset
from agent.session.entry import SessionEntry
from agent.session.status import SessionStatus
from agent.tool_execution import execute_tool_calls
from agent.tools import tool_registry
from agent.tools.toolset import ToolSet
from shared.types import Message

logger = logging.getLogger(__name__)

# Number of consecutive user/assistant exchanges without a task-tool call
# before the system reminds the model to check its task list.
_TASK_STALE_THRESHOLD = 2


# ── Turn-start context helpers ──────────────────────────


def _find_last_skill_content(history: list[dict]) -> str | None:
    """Scan message history (OpenAI-format) from the end for the most recent
    skill summary system message and return its content."""
    for m in reversed(history):
        if m.get("role") != "system":
            continue
        content = m.get("content", "")
        if content.startswith("## Available Skills"):
            return content
    # Fallback: use empty string so first diff always triggers an append
    return ""


def _skills_diff_append(
    hooks,
    *,
    session_id: str,
    turn_id: str,
    history: list[dict],
) -> str | None:
    """Return the skill summary content if it differs from the last written one,
    or None if unchanged. Also emits the system message via hooks."""
    from agent.tools.skill import skill_context_message

    current = skill_context_message()["content"]
    previous = _find_last_skill_content(history)
    if current == previous:
        return None
    return current


def _count_turns_since_last_task_tool(history: list[dict]) -> int:
    """Count user messages since the last assistant message that contained
    a TaskRewrite or TaskUpdate tool call."""
    turns = 0
    for m in reversed(history):
        role = m.get("role", "")
        if role == "user":
            turns += 1
            continue
        if role == "assistant":
            tool_calls = m.get("tool_calls") or []
            for tc in tool_calls:
                name = (tc.get("function") or {}).get("name", "")
                if name in ("TaskRewrite", "TaskUpdate"):
                    return turns
    # No task tool call found at all — count all turns
    return turns


def _tasks_exist(ws, session_id: str) -> bool:
    """Check whether the session has a non-empty task list on disk."""
    try:
        from agent.tools.task import _load_tasks_sync, _tasks_path

        path = _tasks_path(ws, session_id)
        if not path.exists():
            return False
        tasks = _load_tasks_sync(path)
        return len(tasks) > 0
    except Exception:
        return False


_TASK_REMINDER = (
    "Your task list may be stale. "
    "Use TaskList to review current status and continue from the next pending task."
)


# ── Turn executor ───────────────────────────────────────


async def execute_turn(
    runtime,
    entry: SessionEntry,
    question: str,
    max_steps: int,
    shadow_repo=None,
    *,
    top_level: bool = True,
) -> str:
    """Run one ReAct turn for a session."""
    openai_client, default_model_id = runtime._get_llm()
    model_id = entry.config.model_id or default_model_id
    sid = entry.id
    ws = entry.ws
    intr = runtime._interrupt_event
    assert intr is not None

    turn_id = _uuid.uuid4().hex
    final_answer = ""
    total_input_tokens = 0
    total_output_tokens = 0

    await runtime._hooks.on_turn_start(
        turn_id=turn_id,
        session_id=sid,
        user_question=question,
    )

    try:
        # ── 1. Append user message ──────────────────────
        user_id = _uuid.uuid4().hex
        user_msg = Message.user_message(user_id, turn_id, question)
        await runtime._hooks.on_message_start(msg=user_msg, session_id=sid)
        await runtime._hooks.on_chunk_delta(
            msg=user_msg, field="content", delta=question, session_id=sid
        )
        await runtime._hooks.on_chunk_complete(
            msg=user_msg, field="content", full_content=question, session_id=sid
        )
        await runtime._hooks.on_message_finish(msg=user_msg, session_id=sid)

        # ── 2. Load current history for diff checks ─────
        history = build_llm_messages(session_id=sid, workspace=ws)

        # ── 3. Skills diff → append if changed ─────────
        new_skills = _skills_diff_append(
            runtime._hooks,
            session_id=sid,
            turn_id=turn_id,
            history=history,
        )
        if new_skills:
            await emit_system_message(
                runtime._hooks,
                session_id=sid,
                turn_id=turn_id,
                content=new_skills,
            )

        # ── 4. Memory → append ─────────────────────────
        injected = await runtime._hooks.gather_context(
            turn_id=turn_id,
            session_id=sid,
            user_question=question,
        )
        for item in injected:
            if item.get("role") == "system" and item.get("content"):
                await emit_system_message(
                    runtime._hooks,
                    session_id=sid,
                    turn_id=turn_id,
                    content=item["content"],
                )

        # ── 5. Task stale reminder ─────────────────────
        turns_since_task = _count_turns_since_last_task_tool(history)
        if turns_since_task >= _TASK_STALE_THRESHOLD and _tasks_exist(ws, sid):
            await emit_system_message(
                runtime._hooks,
                session_id=sid,
                turn_id=turn_id,
                content=_TASK_REMINDER,
            )

        # ── ReAct loop ─────────────────────────────────
        for _step in range(max_steps):
            if intr.is_set():
                raise InterruptedError("Interrupted by user")

            messages = build_llm_messages(session_id=sid, workspace=ws)

            assistant_id = _uuid.uuid4().hex
            tool_names = entry.config.tool_names()
            toolset = ToolSet(tool_registry, *tool_names) if tool_names else default_toolset()

            streaming_holder: list[Message | None] = [None]
            runtime._streaming_holder = streaming_holder
            assistant_msg, finish_reason = await model_call(
                openai_client,
                model_id,
                sid,
                messages,
                toolset.openai_tools,
                message_id=assistant_id,
                turn_id=turn_id,
                interrupt_event=intr,
                hook_manager=runtime._hooks,
                streaming_holder=streaming_holder,
            )
            runtime._streaming_holder = None

            has_tool_calls = assistant_msg.has_tool_calls
            if assistant_msg.content:
                final_answer = assistant_msg.content

            usage = extract_usage(assistant_msg)
            total_input_tokens += usage.get("prompt_tokens", 0)
            total_output_tokens += usage.get("completion_tokens", 0)

            if finish_reason == "stop":
                break

            if not has_tool_calls:
                await runtime._emit_error_message(
                    session_id=sid,
                    turn_id=turn_id,
                    error="LLM returned no tool_calls and no content.",
                )
                break

            async def invoke_child_agent(
                prompt,
                max_steps=5,
                with_skills=None,
                tool_call_id="",
            ):
                return await runtime.invoke_subagent(
                    sid,
                    prompt,
                    max_steps=max_steps,
                    with_skills=with_skills,
                    parent_message_id=assistant_msg.id,
                    parent_tool_call_id=tool_call_id,
                )

            async def request_human_input(
                payload,
                interrupt_event=None,
                tool_call_id="",
            ):
                return await runtime._ask_user_input(
                    payload,
                    interrupt_event or intr,
                    session_id=sid,
                    turn_id=turn_id,
                    message_id=assistant_msg.id,
                    tool_call_id=tool_call_id,
                )

            await execute_tool_calls(
                assistant_msg=assistant_msg,
                ws=ws,
                toolset=toolset,
                interrupt_event=intr,
                openai_client=openai_client,
                model_id=model_id,
                session_id=sid,
                turn_id=turn_id,
                hook_manager=runtime._hooks,
                ask_guard=runtime._ask_guard,
                invoke_subagent=invoke_child_agent,
                request_human_input=request_human_input,
            )

    except InterruptedError:
        await runtime._finish_partial_streaming_message(session_id=sid)
        error_msg_obj = await runtime._emit_error_message(
            session_id=sid,
            turn_id=turn_id,
            error=(
                "The user interrupted the agent before it could "
                "finish. Summarize what you have done so far and ask "
                "how to proceed."
            ),
        )
        final_answer = error_msg_obj.error
    except Exception as exc:
        logger.warning(
            "AgentRuntime: turn failed with %s: %s",
            type(exc).__name__,
            exc,
        )
        error_msg_obj = await runtime._emit_error_message(
            session_id=sid,
            turn_id=turn_id,
            error=str(exc),
        )
        final_answer = error_msg_obj.error
    finally:
        await runtime._hooks.on_turn_end(
            turn_id=turn_id,
            session_id=sid,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )
        await runtime._hooks.flush()

        runtime._streaming_holder = None
        if top_level:
            runtime._running_session_id = None
            runtime._loop_task = None
        entry.transition_to(SessionStatus.IDLE)
    return final_answer or "SubAgent completed (no output)."
