"""Tool call execution orchestration.

Owns guard checks, effect-based batching, tool-result message
construction, interrupt-aware parallel execution, and single-tool dispatch
(SubAgent / BrowserInspect inlined).
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import uuid as _uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from agent.core.workspace import Workspace
from agent.errors import InterruptedError
from agent.tools import tool_registry
from agent.tools.browser import (
    close_browser_session,
    start_browsergym_session,
)
from agent.tools.result import ToolResult
from agent.tools.toolset import ToolSet
from shared.hooks import GuardCheck, GuardDecision, HookManager
from shared.types import Message, ToolCall

AskGuardFn = Callable[[GuardCheck, asyncio.Event], Awaitable[bool]]
RunChildAgentFn = Callable[..., Awaitable[str]]
InvokeBrowserInspectFn = Callable[..., Awaitable[str]]
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


PathMode = Literal["readonly", "readonly_exec", "readwrite"]


@dataclass
class SysguardAskTracker:
    asked: dict[str, set[PathMode]]

    def can_ask(self, path: str, mode: PathMode) -> bool:
        key = _canonical_rule_path(path)
        modes = self.asked.setdefault(key, set())
        if mode in modes:
            return False
        if mode != "readwrite" and modes:
            return False
        modes.add(mode)
        return True


def _is_parallel_candidate(
    info: ToolCallInfo,
    *,
    allow_browser_inspect: bool = False,
) -> bool:
    if info.name == "BrowserInspect":
        return allow_browser_inspect
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
    workspace: Workspace,
    toolset: ToolSet,
    interrupt_event: asyncio.Event,
    openai_client=None,
    model_id: str = "",
    session_id: str,
    turn_id: str,
    hook_manager: HookManager,
    ask_guard: AskGuardFn,
    request_human_input: RequestHumanInputFn,
    run_child_agent: RunChildAgentFn,
    invoke_browser_inspect: InvokeBrowserInspectFn | None = None,
) -> None:
    """Execute all tool calls for one assistant message.

    Conservative first version:
    - pure read/network/skill tools may run in parallel;
    - all stateful, interactive, browser, shell, task, and write tools run as
      singleton batches;
    - ASK guard decisions force singleton execution.
    """

    infos = [_tool_call_info(tc, idx) for idx, tc in enumerate(assistant_msg.tool_calls)]
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

        allow_browser_inspect = invoke_browser_inspect is not None
        if (
            not _is_parallel_candidate(
                first,
                allow_browser_inspect=allow_browser_inspect,
            )
            or first_decision == GuardDecision.ASK
        ):
            await _run_tool_batch(
                [ToolJob(first, first_decision)],
                assistant_msg=assistant_msg,
                workspace=workspace,
                toolset=toolset,
                interrupt_event=interrupt_event,
                openai_client=openai_client,
                model_id=model_id,
                session_id=session_id,
                turn_id=turn_id,
                hook_manager=hook_manager,
                ask_guard=ask_guard,
                run_child_agent=run_child_agent,
                invoke_browser_inspect=invoke_browser_inspect,
                request_human_input=request_human_input,
            )
            index += 1
            continue

        jobs = [ToolJob(first, first_decision)]
        index += 1

        while index < len(infos):
            next_info = infos[index]
            if not _is_parallel_candidate(
                next_info,
                allow_browser_inspect=allow_browser_inspect,
            ):
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
            workspace=workspace,
            toolset=toolset,
            interrupt_event=interrupt_event,
            openai_client=openai_client,
            model_id=model_id,
            session_id=session_id,
            turn_id=turn_id,
            hook_manager=hook_manager,
            ask_guard=ask_guard,
            run_child_agent=run_child_agent,
            invoke_browser_inspect=invoke_browser_inspect,
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
    workspace: Workspace,
    toolset: ToolSet,
    interrupt_event: asyncio.Event,
    openai_client,
    model_id: str,
    session_id: str,
    turn_id: str,
    hook_manager: HookManager,
    ask_guard: AskGuardFn,
    run_child_agent: RunChildAgentFn,
    invoke_browser_inspect: InvokeBrowserInspectFn | None,
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
            workspace=workspace,
            toolset=toolset,
            interrupt_event=interrupt_event,
            openai_client=openai_client,
            model_id=model_id,
            session_id=session_id,
            turn_id=turn_id,
            hook_manager=hook_manager,
            ask_guard=ask_guard,
            run_child_agent=run_child_agent,
            invoke_browser_inspect=invoke_browser_inspect,
            request_human_input=request_human_input,
            emit_lock=emit_lock,
        )
        return

    tasks = [
        asyncio.create_task(
            _run_tool_job(
                job,
                assistant_msg=assistant_msg,
                workspace=workspace,
                toolset=toolset,
                interrupt_event=interrupt_event,
                openai_client=openai_client,
                model_id=model_id,
                session_id=session_id,
                turn_id=turn_id,
                hook_manager=hook_manager,
                ask_guard=ask_guard,
                run_child_agent=run_child_agent,
                invoke_browser_inspect=invoke_browser_inspect,
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
    workspace: Workspace,
    toolset: ToolSet,
    interrupt_event: asyncio.Event,
    openai_client,
    model_id: str,
    session_id: str,
    turn_id: str,
    hook_manager: HookManager,
    ask_guard: AskGuardFn,
    run_child_agent: RunChildAgentFn,
    invoke_browser_inspect: InvokeBrowserInspectFn | None,
    request_human_input: RequestHumanInputFn,
    emit_lock: asyncio.Lock,
) -> None:
    info = job.info
    tool_output = ""
    tool_status = "success"
    tool_status_source = "tool"
    tool_status_reason = ""
    sysguard_asks = SysguardAskTracker(asked={})

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
            f"Permission denied: tool '{info.name}' is disabled by global tool permissions."
        )
    elif job.guard_decision == GuardDecision.ASK:
        approved = await ask_guard(guard_check, interrupt_event)
        if not approved:
            tool_status = "denied"
            tool_status_source = "user"
            tool_status_reason = "rejected_by_user"
            tool_output = f"Permission denied: user rejected tool '{info.name}'."

    async def job_run_child_agent(
        prompt,
        max_steps=5,
        with_skills=None,
        tool_call_id="",
    ):
        return await run_child_agent(
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
                workspace=workspace,
                assistant_msg=assistant_msg,
                session_id=session_id,
                turn_id=turn_id,
                interrupt_event=interrupt_event,
                ask_guard=ask_guard,
                sysguard_asks=sysguard_asks,
                workspace_uuid=workspace.uuid,
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
                    sysguard_asks=sysguard_asks,
                    workspace_uuid=workspace.uuid,
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
                workspace,
                toolset,
                interrupt_event=interrupt_event,
                openai_client=openai_client,
                model_id=model_id,
                session_id=session_id,
                hook_manager=hook_manager,
                agent_invoker=job_run_child_agent,
                browser_inspector_invoker=invoke_browser_inspect,
                human_input_requester=job_request_human_input,
            )
            tool_output = tool_exec.output
            tool_status = tool_exec.status
            tool_status_source = tool_exec.source
            tool_status_reason = tool_exec.reason
            attempts = 0
            while _is_sysguard_denial(tool_exec) and attempts < 2:
                attempts += 1
                approved = await _ask_shell_sysguard_from_result(
                    info,
                    tool_exec,
                    assistant_msg=assistant_msg,
                    session_id=session_id,
                    turn_id=turn_id,
                    interrupt_event=interrupt_event,
                    ask_guard=ask_guard,
                    sysguard_asks=sysguard_asks,
                    workspace_uuid=workspace.uuid,
                )
                if not approved:
                    break
                tool_exec = await execute_one_tool(
                    info.tc_dict,
                    workspace,
                    toolset,
                    interrupt_event=interrupt_event,
                    openai_client=openai_client,
                    model_id=model_id,
                    session_id=session_id,
                    hook_manager=hook_manager,
                    agent_invoker=job_run_child_agent,
                    browser_inspector_invoker=invoke_browser_inspect,
                    human_input_requester=job_request_human_input,
                )
                tool_output = tool_exec.output
                tool_status = tool_exec.status
                tool_status_source = tool_exec.source
                tool_status_reason = tool_exec.reason
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
    workspace: Workspace,
    assistant_msg: Message,
    session_id: str,
    turn_id: str,
    interrupt_event: asyncio.Event,
    ask_guard: AskGuardFn,
    sysguard_asks: SysguardAskTracker,
    workspace_uuid: str,
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
        candidate = _external_candidate_path(workspace, value, mode)
        if candidate is None:
            continue
        approved = await _ask_and_add_sysguard_rule(
            rule_path=str(candidate),
            label=f"{info.name} {field}",
            description=(
                f"Allow {info.name} to access structured `{field}` path as {mode}: {candidate}"
            ),
            mode=mode,
            info=info,
            assistant_msg=assistant_msg,
            session_id=session_id,
            turn_id=turn_id,
            interrupt_event=interrupt_event,
            ask_guard=ask_guard,
            sysguard_asks=sysguard_asks,
            workspace_uuid=workspace_uuid,
        )
        if not approved:
            return False
    return None


def _external_candidate_path(
    workspace: Workspace,
    value: str,
    mode: Literal["readonly", "readwrite"],
) -> Path | None:
    from agent.utils import sandbox

    raw = Path(value).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else (workspace.root / raw).resolve()
    try:
        resolved.relative_to(workspace.root)
        return None
    except ValueError:
        pass
    if sandbox.is_path_allowed(str(resolved), mode, workspace_uuid=workspace.uuid):
        return None
    if sandbox._overlaps_project_root(resolved):
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
    sysguard_asks: SysguardAskTracker,
    workspace_uuid: str,
) -> bool | None:
    from agent.utils import sandbox

    command = _shell_command_from_args(info.args)
    if not command:
        return None
    rule = sandbox.detect_command_rule(command)
    if rule is None or sandbox.is_path_allowed(
        rule.path,
        workspace_uuid=workspace_uuid,
    ):
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
        sysguard_asks=sysguard_asks,
        workspace_uuid=workspace_uuid,
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
    sysguard_asks: SysguardAskTracker,
    workspace_uuid: str,
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
        sysguard_asks=sysguard_asks,
        workspace_uuid=workspace_uuid,
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
    sysguard_asks: SysguardAskTracker,
    workspace_uuid: str,
) -> bool:
    if not sysguard_asks.can_ask(rule_path, mode):
        return False
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

    with contextlib.suppress(FileExistsError):
        add_custom_sysguard_rule(
            label=label,
            path=rule_path,
            mode=mode,
            description=description,
            enabled=True,
            workspace_uuid=workspace_uuid,
        )
    return True


def _canonical_rule_path(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return str(Path(path).expanduser().absolute())


def _shell_command_from_args(args: str) -> str:
    try:
        data = json.loads(args)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""
    command = data.get("command")
    return command if isinstance(command, str) else ""


# ═══════════════════════════════════════════════════════════
# execute_one_tool — single tool dispatch (moved from actions.py)
# ═══════════════════════════════════════════════════════════


@dataclass
class ToolExecutionResult:
    output: str
    status: str = "success"
    source: str = "tool"
    reason: str = ""
    metadata: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.output

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.output == other
        return super().__eq__(other)

    def __contains__(self, item: object) -> bool:
        return str(item) in self.output


def _coerce_tool_result(result: object) -> ToolExecutionResult:
    if isinstance(result, ToolExecutionResult):
        return result
    if isinstance(result, ToolResult):
        return ToolExecutionResult(
            output=result.output,
            status=result.status,
            source=result.source,
            reason=result.reason,
            metadata=result.metadata,
        )
    return ToolExecutionResult(output=str(result))


async def execute_one_tool(
    tc: dict,
    workspace: Workspace,
    toolset: ToolSet,
    *,
    interrupt_event: asyncio.Event,
    openai_client=None,
    model_id: str = "",
    session_id: str = "",
    hook_manager: HookManager | None = None,
    agent_invoker=None,
    browser_inspector_invoker=None,
    human_input_requester=None,
) -> ToolExecutionResult:
    """Execute a single tool_call. SubAgent / BrowserInspect dispatched inline."""
    func_name: str = tc["function"]["name"]
    func_args: str = tc["function"]["arguments"]

    if interrupt_event.is_set():
        raise InterruptedError("Interrupted before tool execution")

    try:
        tool, args = toolset.parse(func_name, func_args)
    except Exception as exc:
        return ToolExecutionResult(
            output=f"Error parsing {func_name}: {exc}",
            status="error",
            source="runtime",
            reason="parse_failed",
        )

    # ── SubAgent / BrowserInspect: dispatched inline ──
    if tool.name == "SubAgent":
        if agent_invoker is not None:
            result_str = await agent_invoker(
                prompt=args.get("prompt", ""),
                max_steps=args.get("max_steps", 5),
                with_skills=args.get("with_skills", []),
                tool_call_id=tc.get("id", ""),
            )
        else:
            from agent.runtime.subagents import run_inline_subagent

            result_str = await run_inline_subagent(
                workspace,
                toolset,
                prompt=args.get("prompt", ""),
                max_steps=args.get("max_steps", 5),
                openai_client=openai_client,
                model_id=model_id,
                session_id=session_id,
                interrupt_event=interrupt_event,
                with_skills=args.get("with_skills", []),
                hook_manager=hook_manager,
                human_input_requester=human_input_requester,
            )
    elif tool.name == "BrowserInspect":
        inspect_url = args.get("url", "")
        if browser_inspector_invoker is not None:
            result_str = await browser_inspector_invoker(
                url=inspect_url,
                prompt=args.get("prompt", ""),
                max_steps=args.get("max_steps", 8),
                tool_call_id=tc.get("id", ""),
            )
        else:
            browser_toolset = ToolSet(tool_registry, "BrowserObserve", "BrowserAct")
            try:
                open_result = await start_browsergym_session(
                    session_id,
                    url=inspect_url,
                    goal=args.get("prompt", ""),
                    max_bytes=20_000,
                )

                from agent.runtime.subagents import run_inline_subagent

                result_str = await run_inline_subagent(
                    workspace,
                    browser_toolset,
                    prompt=args.get("prompt", ""),
                    max_steps=args.get("max_steps", 8),
                    openai_client=openai_client,
                    model_id=model_id,
                    session_id=session_id,
                    interrupt_event=interrupt_event,
                    hook_manager=hook_manager,
                    system_extra=(
                        "You are a browser inspection sub-agent. Your toolset "
                        "contains ONLY BrowserObserve and BrowserAct. The current "
                        "page has already been opened inside a BrowserGym "
                        "environment. BrowserObserve reads the current page as a "
                        "rich text observation with actionable elements, page "
                        "outline, bbox, and visibility data; it never opens URLs. "
                        "BrowserAct takes a structured action with a primitive "
                        "such as click, fill, keyboard_press, scroll, or goto. "
                        "Prefer bid over CSS selectors for element actions. "
                        f"The page has already been opened at: {inspect_url}\n"
                        "Use BrowserObserve with detail='full' whenever you need "
                        "to inspect the page again. Use the bid values from the "
                        "initial observation. Inspect the current page and report "
                        "what you see. Keep your reasoning extremely brief — one "
                        "short sentence at most."
                        "\n\nInitial page state:\n"
                        f"{open_result}"
                    ),
                    human_input_requester=human_input_requester,
                )
            finally:
                await close_browser_session(session_id)
    else:
        try:
            call_args = dict(args)
            if _accepts_kwarg(tool.coroutine, "workspace"):
                call_args["workspace"] = workspace
            for meta_name, meta_value in (
                ("session_id", session_id),
                ("interrupt_event", interrupt_event),
                ("human_input_requester", human_input_requester),
            ):
                if _accepts_kwarg(tool.coroutine, meta_name):
                    call_args[meta_name] = meta_value
            result_str = await tool.coroutine(**call_args)
        except InterruptedError:
            raise
        except Exception as exc:
            return ToolExecutionResult(
                output=f"Error: {exc}",
                status="error",
                source="tool",
                reason=str(exc),
            )

    return _coerce_tool_result(result_str)


def _accepts_kwarg(fn, name: str) -> bool:
    try:
        params = inspect.signature(fn).parameters.values()
    except TypeError, ValueError:
        return False
    return any(p.kind == inspect.Parameter.VAR_KEYWORD or p.name == name for p in params)
