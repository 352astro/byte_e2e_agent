"""Tool call execution orchestration.

This module owns guard checks, effect-based batching, tool-result message
construction, and interrupt-aware parallel execution. The low-level execution
of a single tool remains in agent.actions.execute_one_tool().
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import uuid as _uuid
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from agent.actions import execute_one_tool
from agent.core.workspace import Workspace
from agent.errors import InterruptedError
from agent.tools.toolset import ToolSet
from shared.hooks import GuardCheck, GuardDecision, HookManager
from shared.types import Message, ToolCall

AskGuardFn = Callable[[GuardCheck, asyncio.Event], Awaitable[bool]]
InvokeSubagentFn = Callable[..., Awaitable[str]]
RequestHumanInputFn = Callable[..., Awaitable[dict]]

_PARALLEL_READ_TOOLS = frozenset(
    {
        "Read",
        "ListDir",
        "Glob",
        "Grep",
        "LoadSkill",
        "WebSearch",
        "WebFetch",
    }
)

_STRUCTURED_PATH_ACCESS: dict[str, dict[str, Literal["readonly", "readwrite"]]] = {
    "Read": {"path": "readonly"},
    "ListDir": {"path": "readonly"},
    "Write": {"path": "readwrite"},
    "Edit": {"path": "readwrite"},
    "Shell": {"cwd": "readwrite"},
}


@dataclass(frozen=True)
class ToolCallInfo:
    index: int
    id: str
    name: str
    args: str

    @property
    def tc_dict(self) -> dict:
        return {
            "id": self.id,
            "function": {"name": self.name, "arguments": self.args},
        }


@dataclass(frozen=True)
class ToolJob:
    info: ToolCallInfo
    guard_decision: GuardDecision | None


def _is_parallel_candidate(info: ToolCallInfo) -> bool:
    return info.name in _PARALLEL_READ_TOOLS


def _tool_call_info(tc: ToolCall, index: int) -> ToolCallInfo:
    return ToolCallInfo(
        index=index,
        id=tc.id or _uuid.uuid4().hex,
        name=tc.function.name,
        args=tc.function.arguments,
    )


async def execute_tool_calls(
    *,
    assistant_msg: Message,
    ws: Workspace,
    toolset: ToolSet,
    interrupt_event: asyncio.Event,
    openai_client=None,
    model_id: str = "",
    session_id: str,
    turn_id: str,
    hook_manager: HookManager,
    ask_guard: AskGuardFn,
    invoke_subagent: InvokeSubagentFn,
    request_human_input: RequestHumanInputFn,
) -> None:
    """Execute all tool calls for one assistant message.

    Conservative first version:
    - pure read/network/skill tools may run in parallel;
    - all stateful, interactive, browser, shell, task, and write tools run as
      singleton batches;
    - ASK guard decisions force singleton execution.
    """

    infos = [
        _tool_call_info(tc, idx) for idx, tc in enumerate(assistant_msg.tool_calls)
    ]
    index = 0
    while index < len(infos):
        if interrupt_event.is_set():
            raise InterruptedError("Interrupted between tools")

        first = infos[index]
        first_decision = await _guard_check(
            first,
            assistant_msg=assistant_msg,
            session_id=session_id,
            turn_id=turn_id,
            hook_manager=hook_manager,
        )

        if not _is_parallel_candidate(first) or first_decision == GuardDecision.ASK:
            await _run_tool_batch(
                [ToolJob(first, first_decision)],
                assistant_msg=assistant_msg,
                ws=ws,
                toolset=toolset,
                interrupt_event=interrupt_event,
                openai_client=openai_client,
                model_id=model_id,
                session_id=session_id,
                turn_id=turn_id,
                hook_manager=hook_manager,
                ask_guard=ask_guard,
                invoke_subagent=invoke_subagent,
                request_human_input=request_human_input,
            )
            index += 1
            continue

        jobs = [ToolJob(first, first_decision)]
        index += 1

        while index < len(infos):
            next_info = infos[index]
            if not _is_parallel_candidate(next_info):
                break
            decision = await _guard_check(
                next_info,
                assistant_msg=assistant_msg,
                session_id=session_id,
                turn_id=turn_id,
                hook_manager=hook_manager,
            )
            if decision == GuardDecision.ASK:
                break
            jobs.append(ToolJob(next_info, decision))
            index += 1

        await _run_tool_batch(
            jobs,
            assistant_msg=assistant_msg,
            ws=ws,
            toolset=toolset,
            interrupt_event=interrupt_event,
            openai_client=openai_client,
            model_id=model_id,
            session_id=session_id,
            turn_id=turn_id,
            hook_manager=hook_manager,
            ask_guard=ask_guard,
            invoke_subagent=invoke_subagent,
            request_human_input=request_human_input,
        )


async def _guard_check(
    info: ToolCallInfo,
    *,
    assistant_msg: Message,
    session_id: str,
    turn_id: str,
    hook_manager: HookManager,
) -> GuardDecision | None:
    check = GuardCheck(
        action_type="tool.execute",
        subject=info.name,
        payload={
            "tool_name": info.name,
            "tool_args": info.args,
        },
        session_id=session_id,
        turn_id=turn_id,
        message_id=assistant_msg.id,
        tool_call_id=info.id,
    )
    return await hook_manager.guard_check(check)


async def _run_tool_batch(
    jobs: list[ToolJob],
    *,
    assistant_msg: Message,
    ws: Workspace,
    toolset: ToolSet,
    interrupt_event: asyncio.Event,
    openai_client,
    model_id: str,
    session_id: str,
    turn_id: str,
    hook_manager: HookManager,
    ask_guard: AskGuardFn,
    invoke_subagent: InvokeSubagentFn,
    request_human_input: RequestHumanInputFn,
) -> None:
    emit_lock = asyncio.Lock()
    for job in jobs:
        await hook_manager.on_chunk_complete(
            msg=assistant_msg,
            field="tool_calls",
            full_content=job.info.args,
            tool_name=job.info.name,
            tool_args=job.info.args,
            session_id=session_id,
        )

    if len(jobs) == 1:
        await _run_tool_job(
            jobs[0],
            assistant_msg=assistant_msg,
            ws=ws,
            toolset=toolset,
            interrupt_event=interrupt_event,
            openai_client=openai_client,
            model_id=model_id,
            session_id=session_id,
            turn_id=turn_id,
            hook_manager=hook_manager,
            ask_guard=ask_guard,
            invoke_subagent=invoke_subagent,
            request_human_input=request_human_input,
            emit_lock=emit_lock,
        )
        return

    tasks = [
        asyncio.create_task(
            _run_tool_job(
                job,
                assistant_msg=assistant_msg,
                ws=ws,
                toolset=toolset,
                interrupt_event=interrupt_event,
                openai_client=openai_client,
                model_id=model_id,
                session_id=session_id,
                turn_id=turn_id,
                hook_manager=hook_manager,
                ask_guard=ask_guard,
                invoke_subagent=invoke_subagent,
                request_human_input=request_human_input,
                emit_lock=emit_lock,
            )
        )
        for job in jobs
    ]
    try:
        for task in asyncio.as_completed(tasks):
            await task
    except InterruptedError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def _run_tool_job(
    job: ToolJob,
    *,
    assistant_msg: Message,
    ws: Workspace,
    toolset: ToolSet,
    interrupt_event: asyncio.Event,
    openai_client,
    model_id: str,
    session_id: str,
    turn_id: str,
    hook_manager: HookManager,
    ask_guard: AskGuardFn,
    invoke_subagent: InvokeSubagentFn,
    request_human_input: RequestHumanInputFn,
    emit_lock: asyncio.Lock,
) -> None:
    info = job.info
    tool_output = ""
    tool_status = "success"
    tool_status_source = "tool"
    tool_status_reason = ""

    guard_check = GuardCheck(
        action_type="tool.execute",
        subject=info.name,
        payload={
            "tool_name": info.name,
            "tool_args": info.args,
        },
        session_id=session_id,
        turn_id=turn_id,
        message_id=assistant_msg.id,
        tool_call_id=info.id,
    )

    if job.guard_decision == GuardDecision.DENY:
        tool_status = "denied"
        tool_status_source = "permission"
        tool_status_reason = "disabled_by_policy"
        tool_output = (
            f"Permission denied: tool '{info.name}' is disabled "
            "by global tool permissions."
        )
    elif job.guard_decision == GuardDecision.ASK:
        approved = await ask_guard(guard_check, interrupt_event)
        if not approved:
            tool_status = "denied"
            tool_status_source = "user"
            tool_status_reason = "rejected_by_user"
            tool_output = f"Permission denied: user rejected tool '{info.name}'."

    async def job_invoke_subagent(
        prompt,
        max_steps=5,
        with_skills=None,
        tool_call_id="",
    ):
        return await invoke_subagent(
            prompt=prompt,
            max_steps=max_steps,
            with_skills=with_skills,
            tool_call_id=tool_call_id or info.id,
        )

    outer_interrupt_event = interrupt_event

    async def job_request_human_input(payload, interrupt_event=None):
        return await request_human_input(
            payload,
            interrupt_event=interrupt_event or outer_interrupt_event,
            tool_call_id=info.id,
        )

    if not tool_output:
        try:
            path_approved = await _ask_structured_paths_if_needed(
                info,
                ws=ws,
                assistant_msg=assistant_msg,
                session_id=session_id,
                turn_id=turn_id,
                interrupt_event=interrupt_event,
                ask_guard=ask_guard,
            )
            if path_approved is False:
                tool_status = "denied"
                tool_status_source = "user"
                tool_status_reason = "sandbox_allow_rejected"
                tool_output = "Permission denied: user rejected sandbox path access."
            if info.name == "Shell":
                preapproved = await _ask_shell_sysguard_if_needed(
                    info,
                    assistant_msg=assistant_msg,
                    session_id=session_id,
                    turn_id=turn_id,
                    interrupt_event=interrupt_event,
                    ask_guard=ask_guard,
                )
                if preapproved is False:
                    tool_status = "denied"
                    tool_status_source = "user"
                    tool_status_reason = "sysguard_allow_rejected"
                    tool_output = "Permission denied: user rejected sysguard allowlist update."
            if tool_output:
                raise _ToolOutputReady()
            tool_exec = await execute_one_tool(
                info.tc_dict,
                ws,
                toolset,
                interrupt_event=interrupt_event,
                openai_client=openai_client,
                model_id=model_id,
                session_id=session_id,
                hook_manager=hook_manager,
                agent_invoker=job_invoke_subagent,
                human_input_requester=job_request_human_input,
            )
            tool_output = tool_exec.output
            tool_status = tool_exec.status
            tool_status_source = tool_exec.source
            tool_status_reason = tool_exec.reason
            if _is_sysguard_denial(tool_exec):
                approved = await _ask_shell_sysguard_from_result(
                    info,
                    tool_exec,
                    assistant_msg=assistant_msg,
                    session_id=session_id,
                    turn_id=turn_id,
                    interrupt_event=interrupt_event,
                    ask_guard=ask_guard,
                )
                if approved:
                    retry_exec = await execute_one_tool(
                        info.tc_dict,
                        ws,
                        toolset,
                        interrupt_event=interrupt_event,
                        openai_client=openai_client,
                        model_id=model_id,
                        session_id=session_id,
                        hook_manager=hook_manager,
                        agent_invoker=job_invoke_subagent,
                        human_input_requester=job_request_human_input,
                    )
                    tool_output = retry_exec.output
                    tool_status = retry_exec.status
                    tool_status_source = retry_exec.source
                    tool_status_reason = retry_exec.reason
        except _ToolOutputReady:
            pass
        except InterruptedError:
            raise
        except Exception as exc:
            tool_status = "error"
            tool_status_source = "tool"
            tool_status_reason = str(exc)
            tool_output = str(exc)

    async with emit_lock:
        await _emit_tool_result(
            info,
            tool_output,
            tool_status=tool_status,
            tool_status_source=tool_status_source,
            tool_status_reason=tool_status_reason,
            turn_id=turn_id,
            session_id=session_id,
            hook_manager=hook_manager,
        )


async def _emit_tool_result(
    info: ToolCallInfo,
    output: str,
    *,
    tool_status: str,
    tool_status_source: str,
    tool_status_reason: str,
    turn_id: str,
    session_id: str,
    hook_manager: HookManager,
) -> None:
    msg = Message.tool_message(
        _uuid.uuid4().hex,
        turn_id,
        info.id,
        info.name,
        output,
        tool_status=tool_status,
        tool_status_source=tool_status_source,
        tool_status_reason=tool_status_reason,
    )
    await hook_manager.on_message_start(msg=msg, session_id=session_id)
    await hook_manager.on_chunk_complete(
        msg=msg,
        field="tool_result",
        full_content=output,
        tool_name=info.name,
        is_error=tool_status != "success",
        tool_status=tool_status,
        tool_status_source=tool_status_source,
        tool_status_reason=tool_status_reason,
        session_id=session_id,
    )
    await hook_manager.on_message_finish(msg=msg, session_id=session_id)


class _ToolOutputReady(Exception):
    pass


def _is_sysguard_denial(tool_exec) -> bool:
    return (
        tool_exec.status == "denied"
        and tool_exec.source == "kernel"
        and tool_exec.reason == "sysguard_denied"
    )


async def _ask_structured_paths_if_needed(
    info: ToolCallInfo,
    *,
    ws: Workspace,
    assistant_msg: Message,
    session_id: str,
    turn_id: str,
    interrupt_event: asyncio.Event,
    ask_guard: AskGuardFn,
) -> bool | None:
    access_by_field = _STRUCTURED_PATH_ACCESS.get(info.name)
    if not access_by_field:
        return None
    try:
        args = json.loads(info.args)
    except json.JSONDecodeError:
        return None
    if not isinstance(args, dict):
        return None

    for field, mode in access_by_field.items():
        value = args.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = _external_candidate_path(ws, value, mode)
        if candidate is None:
            continue
        approved = await _ask_and_add_sysguard_rule(
            rule_path=str(candidate),
            label=f"{info.name} {field}",
            description=(
                f"Allow {info.name} to access structured `{field}` path "
                f"as {mode}: {candidate}"
            ),
            mode=mode,
            info=info,
            assistant_msg=assistant_msg,
            session_id=session_id,
            turn_id=turn_id,
            interrupt_event=interrupt_event,
            ask_guard=ask_guard,
        )
        if not approved:
            return False
    return None


def _external_candidate_path(
    ws: Workspace,
    value: str,
    mode: Literal["readonly", "readwrite"],
) -> Path | None:
    from agent.utils import sysguard

    raw = Path(value).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else (ws.root / raw).resolve()
    try:
        resolved.relative_to(ws.root)
        return None
    except ValueError:
        pass
    if sysguard.is_path_allowed(str(resolved), mode):
        return None
    if sysguard._overlaps_project_root(resolved):
        return None
    return resolved


async def _ask_shell_sysguard_if_needed(
    info: ToolCallInfo,
    *,
    assistant_msg: Message,
    session_id: str,
    turn_id: str,
    interrupt_event: asyncio.Event,
    ask_guard: AskGuardFn,
) -> bool | None:
    from agent.utils import sysguard

    command = _shell_command_from_args(info.args)
    if not command:
        return None
    rule = sysguard.detect_command_rule(command)
    if rule is None or sysguard.is_path_allowed(rule.path):
        return None
    return await _ask_and_add_sysguard_rule(
        rule_path=rule.path,
        label=rule.label,
        description=rule.description,
        mode="readonly_exec",
        info=info,
        assistant_msg=assistant_msg,
        session_id=session_id,
        turn_id=turn_id,
        interrupt_event=interrupt_event,
        ask_guard=ask_guard,
    )


async def _ask_shell_sysguard_from_result(
    info: ToolCallInfo,
    tool_exec,
    *,
    assistant_msg: Message,
    session_id: str,
    turn_id: str,
    interrupt_event: asyncio.Event,
    ask_guard: AskGuardFn,
) -> bool:
    metadata = tool_exec.metadata or {}
    path = str(metadata.get("path") or "")
    if not path:
        return False
    mode = str(metadata.get("mode") or "readonly_exec")
    if mode not in {"readonly", "readonly_exec", "readwrite"}:
        mode = "readonly_exec"
    return await _ask_and_add_sysguard_rule(
        rule_path=path,
        label=str(metadata.get("label") or "Shell toolchain"),
        description=str(metadata.get("description") or "Detected from shell denial."),
        mode=mode,
        info=info,
        assistant_msg=assistant_msg,
        session_id=session_id,
        turn_id=turn_id,
        interrupt_event=interrupt_event,
        ask_guard=ask_guard,
    )


async def _ask_and_add_sysguard_rule(
    *,
    rule_path: str,
    label: str,
    description: str,
    mode: Literal["readonly", "readonly_exec", "readwrite"],
    info: ToolCallInfo,
    assistant_msg: Message,
    session_id: str,
    turn_id: str,
    interrupt_event: asyncio.Event,
    ask_guard: AskGuardFn,
) -> bool:
    check = GuardCheck(
        action_type="sandbox.allow_path",
        subject=info.name,
        payload={
            "kind": "permission_request",
            "title": "Allow sandbox path",
            "description": (
                "The tool needs access to a path outside the current workspace. "
                "Allow it and continue?"
            ),
            "path": rule_path,
            "label": label,
            "mode": mode,
            "choices": [
                {"id": "allow", "label": "Allow", "description": rule_path},
                {"id": "deny", "label": "Deny", "description": "Keep blocked."},
            ],
        },
        session_id=session_id,
        turn_id=turn_id,
        message_id=assistant_msg.id,
        tool_call_id=info.id,
    )
    approved = await ask_guard(check, interrupt_event)
    if not approved:
        return False
    from app.services.settings_service import add_custom_sysguard_rule

    try:
        add_custom_sysguard_rule(
            label=label,
            path=rule_path,
            mode=mode,
            description=description,
            enabled=True,
        )
    except FileExistsError:
        pass
    return True


def _shell_command_from_args(args: str) -> str:
    try:
        data = json.loads(args)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""
    command = data.get("command")
    return command if isinstance(command, str) else ""
