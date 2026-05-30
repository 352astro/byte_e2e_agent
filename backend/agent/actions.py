"""ReAct 引擎原语：思考 → 行动 → 子代理。

所有函数均无状态，依赖显式传入。从 scheduler 抽离以便独立测试和复用。
"""

from __future__ import annotations

import asyncio
import uuid as _uuid

from agent.errors import InterruptedError, ToolMismatchError, repair_transcripts
from agent.llm import HelloAgentsLLM
from agent.metrics import LLMCallContext
from agent.sandbox import Sandbox
from agent.session import Session
from agent.tools import BrowserInspect, TaskList, TaskRewrite
from agent.tools.subagent import SubAgent
from agent.tools.toolset import ToolSet
from agent.transcript import TranscriptStream

_SUBAGENT_DEBUG = True  # 设为 False 关闭子智能体控制台调试输出


# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════


def _default_toolset() -> ToolSet:
    from agent.tools import get_all_tool_classes as _all

    return ToolSet(_all())


async def _apply_repairs(session: Session, channel: TranscriptStream, *stages) -> None:
    old = session._transcripts
    repaired = repair_transcripts(old, *stages)
    new = repaired[len(old) :]
    for rt in new:
        try:
            flushed = await channel.flush(rt.id, rt.kind, base=rt.message)
            session.add_transcript(
                flushed.kind, flushed.message, flushed.id, flushed.commit_sha
            )
        except Exception:
            pass


async def _debug_bridge_silent(silent: TranscriptStream, label: str) -> None:
    if not _SUBAGENT_DEBUG:
        return
    q = silent.subscribe()
    try:
        while True:
            ev = await q.get()
            if ev is None:
                break
            if ev.name == "chunk":
                text = ev.payload.get("text", "")
                if text:
                    print(text, end="", flush=True)
            elif ev.name == "flush":
                print()
    except asyncio.CancelledError:
        pass
    finally:
        silent.unsubscribe(q)


# ═══════════════════════════════════════════════════════════
# 核心
# ═══════════════════════════════════════════════════════════


async def model_call(
    llm_client: HelloAgentsLLM,
    session_id: str,
    channel: TranscriptStream,
    messages: list[dict],
    tools: list[dict],
    transcript_id: str,
    *,
    interrupt_event: asyncio.Event,
) -> str | None:
    """流式调用 LLM，全部 chunk 进入 channel。返回 finish_reason。"""
    finish_reason: str | None = None

    async for ev in llm_client.think_stream(
        messages=messages,
        tools=tools,
        metrics_context=LLMCallContext(
            session_id=session_id,
            transcript_id=transcript_id,
            call_type="agent_step",
        ),
    ):
        if interrupt_event.is_set():
            raise InterruptedError("Interrupted during LLM call")
        if ev["kind"] == "reasoning":
            await channel.chunk(transcript_id, "thinking", ev["token"])
        elif ev["kind"] == "content":
            await channel.chunk(transcript_id, "response", ev["token"])
        elif ev["kind"] == "tool_call_chunk":
            tc = ev["tool_call"]
            idx: int = tc.get("index", 0)
            tool_id = f"{transcript_id}/tc/{idx}"

            msg = channel.ensure_open(transcript_id)
            calls = msg.setdefault("tool_calls", [])
            while len(calls) <= idx:
                calls.append(
                    {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                )
            if tc.get("id"):
                calls[idx]["id"] = tc["id"]

            fn = tc.get("function", {})
            if fn.get("name"):
                await channel.chunk(
                    transcript_id,
                    "tool_name",
                    fn["name"],
                    chunk_id=tool_id,
                )
            if fn.get("arguments"):
                await channel.chunk(
                    transcript_id,
                    "tool_arguments",
                    fn["arguments"],
                    chunk_id=tool_id,
                )
        elif ev["kind"] == "finish_reason":
            finish_reason = ev["finish_reason"]

    msg = channel.message
    content = msg.get("content", "") if msg else ""
    if (
        content
        and "tool" in content.lower()
        and ("mismatch" in content.lower() or "not found" in content.lower())
    ):
        raise ToolMismatchError(content.strip())

    return finish_reason


async def execute_one_tool(
    tc: dict,
    sandbox: Sandbox,
    toolset: ToolSet,
    channel: TranscriptStream,
    *,
    interrupt_event: asyncio.Event,
    llm_client: HelloAgentsLLM,
) -> None:
    """执行单个 tool_call。"""
    func_name: str = tc["function"]["name"]
    func_args: str = tc["function"]["arguments"]
    result_id = _uuid.uuid4().hex

    if interrupt_event.is_set():
        raise InterruptedError("Interrupted before tool execution")

    try:
        action = toolset.parse(func_name, func_args)
    except Exception as exc:
        await channel.chunk(
            result_id,
            "tool_result",
            f"Error parsing {func_name}: {exc}",
            chunk_id=result_id,
        )
        return

    try:
        result_str = await action.execute(
            sandbox=sandbox,
            channel=channel,
            interrupt_event=interrupt_event,
            toolset=toolset,
            result_id=result_id,
            llm_client=llm_client,
        )
    except Exception as exc:
        result_str = f"Error: {exc}"

    if result_str:
        await channel.chunk(
            result_id,
            "tool_result",
            result_str,
            chunk_id=result_id,
        )


async def run_subagent(
    sandbox: Sandbox,
    toolset: ToolSet,
    channel: TranscriptStream,
    prompt: str,
    max_steps: int,
    *,
    llm_client: HelloAgentsLLM,
    session_id: str,
    interrupt_event: asyncio.Event,
    with_skills: list[str] | None = None,
    system_extra: str | None = None,
) -> str:
    """在同一个 session 内运行子智能体。从空白上下文启动。"""
    from agent.tools.skill import get_skill

    subagent_tools = toolset.without(
        SubAgent, BrowserInspect, TaskRewrite, TaskList
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

        silent = TranscriptStream()
        stream_id = _uuid.uuid4().hex

        dbg_task: asyncio.Task | None = None
        if _SUBAGENT_DEBUG:
            dbg_task = asyncio.create_task(
                _debug_bridge_silent(silent, f"s{step}"),
                name=f"subagent_debug_{step}",
            )

        finish_reason = await model_call(
            llm_client,
            session_id,
            silent,
            subagent_messages,
            subagent_tools,
            transcript_id=stream_id,
            interrupt_event=interrupt_event,
        )

        if dbg_task is not None:
            silent.close()
            try:
                await asyncio.wait_for(dbg_task, timeout=2)
            except asyncio.TimeoutError:
                dbg_task.cancel()

        msg = silent.message or {}
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls", [])

        if content:
            last_answer = content

        if finish_reason == "stop" or not tool_calls:
            break

        subagent_messages.append(
            {
                "role": "assistant",
                "content": content or None,
                "tool_calls": tool_calls,
                **(
                    {"reasoning_content": msg["reasoning_content"]}
                    if msg.get("reasoning_content")
                    else {}
                ),
            }
        )

        for tc in tool_calls:
            if interrupt_event.is_set():
                break
            await execute_one_tool(
                tc,
                sandbox,
                toolset,
                silent,
                interrupt_event=interrupt_event,
                llm_client=llm_client,
            )
            result = (silent.message or {}).get("result", "")
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
