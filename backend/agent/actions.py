"""ReAct 引擎原语：思考 → 行动 → 子代理。

纯 openai 实现。所有函数无状态，依赖显式传入。
"""

from __future__ import annotations

import asyncio
import inspect
import uuid as _uuid

from agent.core.workspace import Workspace
from agent.errors import InterruptedError
from agent.tools import tool_registry
from agent.tools.toolset import ToolSet
from shared.hooks import HookManager
from shared.types import Message, ToolCall

_SUBAGENT_DEBUG = True  # 设为 False 关闭子智能体控制台调试输出


# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════


def _default_toolset() -> ToolSet:
    return ToolSet(tool_registry)


async def _debug_bridge_silent(msg: Message | None, label: str) -> None:
    """子智能体调试输出（简化版）。"""
    if not _SUBAGENT_DEBUG or msg is None:
        return
    if msg.content:
        print(msg.content, end="", flush=True)
    if msg.tool_calls:
        for tc in msg.tool_calls:
            print(f"\n[{label}] 🔧 {tc.function.name}")


# ═══════════════════════════════════════════════════════════
# model_call — OpenAI streaming
# ═══════════════════════════════════════════════════════════


async def model_call(
    client,  # openai.OpenAI
    model_id: str,
    session_id: str,
    messages: list[dict],
    tools: list[dict],
    message_id: str,
    *,
    turn_id: str = "",
    interrupt_event: asyncio.Event,
    hook_manager: HookManager | None = None,
    streaming_holder: list[Message | None] | None = None,
) -> tuple[Message, str | None]:
    """流式调用 LLM（原生 openai），直接构建 Message + hook 分发。

    若提供 streaming_holder（单元素列表），会在流式构建期间持续更新
    streaming_holder[0] 为当前 Message，调用方可通过此引用获取正在
    构建中的消息（供 /recover 等端点使用）。

    返回 (msg, finish_reason)。
    """

    finish_reason: str | None = None

    # ── 创建 Message ──────────────────────────────
    msg = Message.assistant_message(message_id, turn_id or message_id)
    if streaming_holder is not None:
        streaming_holder[0] = msg
    if hook_manager is not None:
        await hook_manager.on_message_start(msg=msg, session_id=session_id)

    kwargs: dict = dict(
        model=model_id,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
        reasoning_effort="high",
        extra_body={"thinking": {"type": "enabled"}},
    )
    if tools:
        kwargs["tools"] = tools

    stream = client.chat.completions.create(**kwargs)

    for chunk in stream:
        if interrupt_event.is_set():
            raise InterruptedError("Interrupted during LLM call")

        delta = chunk.choices[0].delta if chunk.choices else None
        if delta is None:
            continue

        _content = getattr(delta, "content", None) or ""
        _reasoning = getattr(delta, "reasoning_content", None) or ""
        _tool_calls = getattr(delta, "tool_calls", None) or []
        _finish = getattr(chunk.choices[0], "finish_reason", None) or ""
        _usage = getattr(chunk, "usage", None)

        # ── reasoning ────────────────────────────────
        if _reasoning:
            msg.reasoning += _reasoning
            if hook_manager is not None:
                await hook_manager.on_chunk_delta(
                    msg=msg, field="reasoning", delta=_reasoning
                )

        # ── text content ─────────────────────────────
        if _content:
            msg.content += _content
            if hook_manager is not None:
                await hook_manager.on_chunk_delta(
                    msg=msg, field="content", delta=_content
                )

        # ── tool calls ───────────────────────────────
        for tc in _tool_calls:
            idx = getattr(tc, "index", 0)
            tc_id = getattr(tc, "id", None) or ""
            tc_fn = getattr(tc, "function", None)
            tc_name = getattr(tc_fn, "name", None) or "" if tc_fn else ""
            tc_args = getattr(tc_fn, "arguments", None) or "" if tc_fn else ""

            while len(msg.tool_calls) <= idx:
                msg.tool_calls.append(ToolCall())
            if tc_id:
                msg.tool_calls[idx].id = tc_id

            if tc_name:
                msg.tool_calls[idx].function.name += tc_name
                if hook_manager is not None:
                    await hook_manager.on_chunk_delta(
                        msg=msg,
                        field="tool_calls",
                        delta=tc_name,
                        tool_name=msg.tool_calls[idx].function.name,
                        tool_index=idx,
                        sub_field="name",
                    )

            if tc_args:
                msg.tool_calls[idx].function.arguments += tc_args
                if hook_manager is not None:
                    await hook_manager.on_chunk_delta(
                        msg=msg,
                        field="tool_calls",
                        delta=tc_args,
                        tool_name=msg.tool_calls[idx].function.name,
                        tool_index=idx,
                        sub_field="args",
                    )

        if _finish:
            finish_reason = _finish

        if _usage and not hasattr(msg, "_usage"):
            # openai returns CompletionUsage (Pydantic object), normalize to dict
            if hasattr(_usage, "prompt_tokens"):
                object.__setattr__(
                    msg,
                    "_usage",
                    {
                        "prompt_tokens": getattr(_usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(_usage, "completion_tokens", 0),
                        "total_tokens": getattr(_usage, "total_tokens", 0),
                    },
                )
            else:
                object.__setattr__(msg, "_usage", _usage)

    # ── 完成 ──────────────────────────────────────
    msg.mark_complete()
    if streaming_holder is not None:
        streaming_holder[0] = None
    if hook_manager is not None:
        usage = getattr(msg, "_usage", None) or {}
        await hook_manager.on_message_finish(
            msg=msg,
            finish_reason=finish_reason or "stop",
            usage=usage,
            session_id=session_id,
        )

    return msg, finish_reason


# ═══════════════════════════════════════════════════════════
# execute_one_tool
# ═══════════════════════════════════════════════════════════


async def execute_one_tool(
    tc: dict,
    ws: Workspace,
    toolset: ToolSet,
    *,
    interrupt_event: asyncio.Event,
    openai_client=None,  # openai.OpenAI
    model_id: str = "",
    session_id: str = "",
    hook_manager: HookManager | None = None,
) -> str:
    """执行单个 tool_call。SubAgent / BrowserInspect 原地分发。返回结果字符串。"""
    func_name: str = tc["function"]["name"]
    func_args: str = tc["function"]["arguments"]
    result_id = _uuid.uuid4().hex

    if interrupt_event.is_set():
        raise InterruptedError("Interrupted before tool execution")

    try:
        tool, args = toolset.parse(func_name, func_args)
    except Exception as exc:
        return f"Error parsing {func_name}: {exc}"

    # ── SubAgent / BrowserInspect：原地分发，不调 handler ──
    if tool.name == "SubAgent":
        result_str = await run_subagent(
            ws,
            toolset,
            prompt=args.get("prompt", ""),
            max_steps=args.get("max_steps", 5),
            openai_client=openai_client,
            model_id=model_id,
            session_id=session_id,
            interrupt_event=interrupt_event,
            with_skills=args.get("with_skills", []),
            hook_manager=hook_manager,
        )
    elif tool.name == "BrowserInspect":
        browser_toolset = ToolSet(tool_registry, "BrowserOpen", "BrowserAct")
        result_str = await run_subagent(
            ws,
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
                "contains ONLY browser tools (BrowserOpen, BrowserAct). "
                "Keep your reasoning extremely brief — one short sentence "
                "at most — then call BrowserOpen to open the page. "
                "After the page loads, inspect what was asked and report "
                "what you see. Do not plan. Do not summarize at length. "
                "Open the browser, check, report. That is your entire job."
            ),
        )
    else:
        try:
            # 注入 workspace 和 session_id 到工具 handler
            call_args = dict(args)
            for meta_name, meta_value in (
                ("ws", ws),
                ("session_id", session_id),
                ("interrupt_event", interrupt_event),
            ):
                if _accepts_kwarg(tool.coroutine, meta_name):
                    call_args[meta_name] = meta_value
            result_str = await tool.coroutine(**call_args)
        except InterruptedError:
            raise
        except Exception as exc:
            result_str = f"Error: {exc}"

    return result_str


def _accepts_kwarg(fn, name: str) -> bool:
    try:
        params = inspect.signature(fn).parameters.values()
    except TypeError, ValueError:
        return False
    return any(
        p.kind == inspect.Parameter.VAR_KEYWORD or p.name == name for p in params
    )


# ═══════════════════════════════════════════════════════════
# run_subagent
# ═══════════════════════════════════════════════════════════


async def run_subagent(
    ws: Workspace,
    toolset: ToolSet,
    prompt: str,
    max_steps: int,
    *,
    openai_client=None,  # openai.OpenAI
    model_id: str = "",
    session_id: str,
    interrupt_event: asyncio.Event,
    with_skills: list[str] | None = None,
    system_extra: str | None = None,
    hook_manager: HookManager | None = None,
) -> str:
    """在同一个 session 内运行子智能体。从空白上下文启动。"""
    from agent.tools.skill import get_skill

    subagent_tools = toolset.without(
        "SubAgent", "BrowserInspect", "TaskList", "TaskRewrite"
    ).openai_tools

    subagent_messages: list[dict] = [
        {
            "role": "system",
            "content": (
                "You are a sub-agent. Complete the assigned task "
                "and return a final answer."
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
    step = 0

    for _ in range(max_steps):
        if interrupt_event.is_set():
            break
        step += 1

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
        tool_calls = (
            [tc.model_dump() for tc in msg.tool_calls] if msg.tool_calls else []
        )

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
                hook_manager=hook_manager,
            )
            subagent_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                }
            )

    return (
        f"SubAgent completed. Result: {last_answer}"
        if last_answer
        else "SubAgent completed (no output)."
    )
