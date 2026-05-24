"""Scheduler — 单例执行调度器。

一个 Project 只有一个 Scheduler，一次只运行一个 Session。
每次 start() 创建新的 StreamTranscriptCompletion（per-session 临时通道）。
Transcript 持久化存储在 Session 中。
"""

from __future__ import annotations

import asyncio
import json
import uuid as _uuid
from dataclasses import dataclass, field

from agent.metrics import LLMCallContext
from agent.session import Session
from agent.tools.shell import get_platform_hint
from agent.tools.skill import skill_context_message
from agent.tools.subtask import SubTask
from agent.tools.task import task_context_message
from agent.tools.toolset import ToolSet
from agent.transcript import StreamTranscriptCompletion

# ── System prompt（只定义一次）─────────────────────────────

SYSTEM_PROMPT = """\
You are an intelligent assistant capable of using external tools and following a plan.
Use the provided functions to interact with the system.

## Rules
- Pick the function that best fits the current situation.
- SubTask    — delegate to a fresh sub-agent
- Shell / Read / Write / Edit / Search / LoadSkill — executable tools
- Follow runtime context messages for platform details, available skills, and current tasks.
"""


def _default_toolset() -> ToolSet:
    from agent.tools import get_all_tool_classes as _all

    return ToolSet(_all())


# ── Internal helpers ──────────────────────────────────────


@dataclass
class _LLMOutput:
    content: str = ""
    reasoning: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str | None = None


# ============================================================
# Scheduler
# ============================================================


class Scheduler:
    """Per-Project 执行调度器（单例）。

    一次只允许一个 Session 在运行。
    StreamTranscriptCompletion 是 per-execution 的临时通道。
    """

    def __init__(self) -> None:
        self._state: str = "idle"
        self._loop_task: asyncio.Task | None = None
        self._pending: dict[str, dict] = {}
        self._current_session: Session | None = None
        self._current_channel: StreamTranscriptCompletion | None = None

    # ── public ────────────────────────────────────────────

    @property
    def channel(self) -> StreamTranscriptCompletion | None:
        """当前运行中 session 的临时通道。"""
        return self._current_channel

    @property
    def state(self) -> str:
        return self._state

    @property
    def pending_request(self) -> dict | None:
        if self._state != "awaiting_input":
            return None
        # 返回第一个待处理请求
        for tid, pending in self._pending.items():
            return {
                "transcript_id": tid,
                "kind": pending.get("kind", "permission_request"),
                "message": pending.get("message", {}),
            }
        return None

    def is_running_session(self, session_id: str) -> bool:
        return (
            self._state != "idle"
            and self._current_session is not None
            and self._current_session.session_id == session_id
        )

    def start(
        self,
        session: Session,
        question: str,
        channel: StreamTranscriptCompletion | None = None,
    ) -> str:
        """启动 session 执行。可传入外部创建的 channel（subscribe-before-start 模式）。"""
        if self._state != "idle":
            raise RuntimeError(f"Scheduler already running (state={self._state})")
        self._current_session = session
        self._current_channel = (
            channel if channel is not None else StreamTranscriptCompletion()
        )
        self._state = "running"
        self._loop_task = asyncio.create_task(
            self._query_loop(question),
            name="sched",
        )
        self._loop_task.add_done_callback(self._on_done)
        return session.session_id

    def resolve(self, transcript_id: str, response: dict) -> None:
        """响应待处理的权限请求。"""
        pending = self._pending.get(transcript_id)
        if pending is None:
            raise KeyError(f"No pending request: {transcript_id}")
        pending["response"] = response
        pending["event"].set()

    # ============================================================
    # query loop
    # ============================================================

    async def _query_loop(self, question: str) -> None:
        session = self._current_session
        channel = self._current_channel
        assert session is not None and channel is not None

        try:
            # ── 1. 保存 user question transcript ─────────
            user_id = _uuid.uuid4().hex
            user_msg = {"role": "user", "content": question}
            t = await channel.flush(user_id, "user_question", user_msg)

            session.add_transcript(t.kind, t.message, t.id)

            max_steps = 50

            for _ in range(max_steps):
                # ── 构建消息 ──────────────────────────
                messages: list[dict] = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "system", "content": f"## Platform\n{get_platform_hint()}"},
                    skill_context_message(),
                    task_context_message(session._sandbox),
                ]
                messages.extend(session.get_messages())

                # ── 模型调用（流式）────────────────────
                assistant_id = _uuid.uuid4().hex
                output = await self._model_call(
                    session,
                    channel,
                    messages,
                    session._toolset.openai_tools,
                    transcript_id=assistant_id,
                )

                # ── 构建并保存 assistant transcript ───
                assistant_msg: dict = {
                    "role": "assistant",
                    "content": output.content or None,
                }
                if output.tool_calls:
                    assistant_msg["tool_calls"] = output.tool_calls
                if output.reasoning:
                    assistant_msg["reasoning_content"] = output.reasoning
                t = await channel.flush(assistant_id, "assistant", assistant_msg)

                session.add_transcript(t.kind, t.message, t.id)

                # ── finish_reason == "stop" → 结束 ────
                if output.finish_reason == "stop":
                    return

                # ── 无 tool_calls → 错误 ──────────────
                if not output.tool_calls:
                    err_id = _uuid.uuid4().hex
                    err_msg = {"message": "LLM returned no tool_calls and no content."}
                    t = await channel.flush(err_id, "error", err_msg)

                    session.add_transcript(t.kind, t.message, t.id)
                    return

                # ── 执行每个 tool_call ─────────────────
                for tc in output.tool_calls:
                    await self._execute_one_tool(tc, session, channel)

        except Exception as exc:
            import traceback

            traceback.print_exc()
            try:
                err_id = _uuid.uuid4().hex
                err_msg = {"message": str(exc)}
                t = await channel.flush(err_id, "error", err_msg)

                session.add_transcript(t.kind, t.message, t.id)
            except Exception:
                pass
        finally:
            self._state = "idle"
            self._loop_task = None
            if self._current_channel is channel:
                channel.close()
                self._current_channel = None

    # ============================================================
    # model call
    # ============================================================

    async def _model_call(
        self,
        session: Session,
        channel: StreamTranscriptCompletion,
        messages: list[dict],
        tools: list[dict],
        transcript_id: str,
    ) -> _LLMOutput:
        """流式调用 LLM，chunk 进入 channel（使用单一 transcript_id）。

        只负责流式输出累积，不保存 transcript 也不 flush。
        调用者负责用同一 transcript_id 执行 add_transcript + flush。
        """
        output = _LLMOutput()

        async for ev in session.llm_client.think_stream(
            messages=messages,
            tools=tools,
            metrics_context=LLMCallContext(
                session_id=session.session_id,
                transcript_id=transcript_id,
                call_type="agent_step",
            ),
        ):
            if ev["kind"] == "reasoning":
                output.reasoning += ev["token"]
                await channel.chunk(transcript_id, "thinking", ev["token"])
            elif ev["kind"] == "content":
                output.content += ev["token"]
                await channel.chunk(transcript_id, "response", ev["token"])
            elif ev["kind"] == "tool_call_chunk":
                tc = ev["tool_call"]
                idx: int = tc.get("index", 0)
                while len(output.tool_calls) <= idx:
                    output.tool_calls.append(
                        {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    )
                if tc.get("id"):
                    output.tool_calls[idx]["id"] = tc["id"]
                fn = tc.get("function", {})
                tool_id = f"{transcript_id}/tc/{idx}"
                if fn.get("name"):
                    output.tool_calls[idx]["function"]["name"] += fn["name"]
                    # 每次收到 name 增量都推送完整累积名称
                    await channel.chunk(
                        transcript_id,
                        "tool_name",
                        output.tool_calls[idx]["function"]["name"],
                        chunk_id=tool_id,
                    )
                if fn.get("arguments"):
                    output.tool_calls[idx]["function"]["arguments"] += fn["arguments"]
                    await channel.chunk(
                        transcript_id,
                        "tool_arguments",
                        fn["arguments"],
                        chunk_id=tool_id,
                    )
            elif ev["kind"] == "finish_reason":
                output.finish_reason = ev["finish_reason"]

        return output

    # ============================================================
    # tool execution
    # ============================================================

    async def _execute_one_tool(
        self,
        tc: dict,
        session: Session,
        channel: StreamTranscriptCompletion,
    ) -> None:
        func_name: str = tc["function"]["name"]
        func_args: str = tc["function"]["arguments"]
        tool_call_id: str = tc["id"]

        try:
            action = session._toolset.parse(func_name, func_args)
        except Exception as exc:
            result = f"Error parsing {func_name}: {exc}"
            result_id = _uuid.uuid4().hex
            result_msg = {
                "tool_call_id": tool_call_id,
                "tool_name": func_name,
                "arguments": func_args,
                "result": result,
            }
            t = await channel.flush(result_id, "tool_result", result_msg)

            session.add_transcript(t.kind, t.message, t.id)
            return

        # ── Shell（流式输出）───────────────────────────
        if func_name == "Shell":
            output_parts: list[str] = []
            result_id = _uuid.uuid4().hex
            async for chunk_text in session._sandbox.stream_shell(
                action.command, action.timeout_ms
            ):
                output_parts.append(chunk_text)
                await channel.chunk(
                    result_id, "tool_result", chunk_text, chunk_id=result_id
                )
            exit_code = session._sandbox.terminal._last_exit_code
            raw = "".join(output_parts)
            result_str = (
                f"{raw.rstrip()}\n[exit code: {exit_code}]"
                if exit_code != 0
                else raw.rstrip() or "(no output)"
            )
            result_msg = {
                "tool_call_id": tool_call_id,
                "tool_name": func_name,
                "arguments": func_args,
                "result": result_str,
            }
            t = await channel.flush(result_id, "tool_result", result_msg)

            session.add_transcript(t.kind, t.message, t.id)
            return

        # ── SubTask（递归子任务）───────────────────────
        if func_name == "SubTask":
            result_str = await self._run_subtask(
                session, channel, action.prompt, action.max_steps
            )
            result_id = _uuid.uuid4().hex
            result_msg = {
                "tool_call_id": tool_call_id,
                "tool_name": func_name,
                "arguments": func_args,
                "result": result_str,
            }
            t = await channel.flush(result_id, "tool_result", result_msg)

            session.add_transcript(t.kind, t.message, t.id)
            return

        # ── 其他工具 ───────────────────────────────────
        try:
            result_str = await action.execute(sandbox=session._sandbox)
        except Exception as exc:
            result_str = f"Error: {exc}"

        result_id = _uuid.uuid4().hex
        result_msg = {
            "tool_call_id": tool_call_id,
                "tool_name": func_name,
                "arguments": func_args,
            "result": result_str,
        }
        t = await channel.flush(result_id, "tool_result", result_msg)

        session.add_transcript(t.kind, t.message, t.id)

    # ============================================================
    # SubTask
    # ============================================================

    async def _run_subtask(
        self,
        parent_session: Session,
        channel: StreamTranscriptCompletion,
        prompt: str,
        max_steps: int,
    ) -> str:
        """在同一个 session 内运行子任务。

        子任务使用受限工具集（无 SubTask），
        transcripts 写入父 session。
        """
        subtask_tools = parent_session._toolset.without(SubTask).openai_tools

        # 子任务的临时消息列表（独立上下文）
        subtask_messages: list[dict] = [
            {
                "role": "system",
                "content": "You are a sub-agent. Complete the assigned task and return a final answer.",
            },
            {"role": "user", "content": prompt},
        ]

        last_answer = ""
        subtask_stream_id = _uuid.uuid4().hex

        for _ in range(max_steps):
            output = _LLMOutput()

            async for ev in parent_session.llm_client.think_stream(
                messages=subtask_messages,
                tools=subtask_tools,
                metrics_context=LLMCallContext(
                    session_id=parent_session.session_id,
                    transcript_id=subtask_stream_id,
                    call_type="subtask_step",
                ),
            ):
                if ev["kind"] == "content":
                    output.content += ev["token"]
                    await channel.chunk(
                        subtask_stream_id,
                        "response",
                        ev["token"],
                        chunk_id=subtask_stream_id,
                    )
                elif ev["kind"] == "tool_call_chunk":
                    tc = ev["tool_call"]
                    idx: int = tc.get("index", 0)
                    while len(output.tool_calls) <= idx:
                        output.tool_calls.append(
                            {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        )
                    if tc.get("id"):
                        output.tool_calls[idx]["id"] = tc["id"]
                    fn = tc.get("function", {})
                    if fn.get("name"):
                        output.tool_calls[idx]["function"]["name"] += fn["name"]
                    if fn.get("arguments"):
                        output.tool_calls[idx]["function"]["arguments"] += fn[
                            "arguments"
                        ]
                elif ev["kind"] == "finish_reason":
                    output.finish_reason = ev["finish_reason"]

            if output.content:
                last_answer = output.content

            if output.finish_reason == "stop":
                break

            if not output.tool_calls:
                break

            # 添加 assistant 消息到子任务上下文
            subtask_messages.append(
                {
                    "role": "assistant",
                    "content": output.content or None,
                    "tool_calls": output.tool_calls,
                }
            )

            # 执行工具
            for tc in output.tool_calls:
                func_name = tc["function"]["name"]
                func_args = tc["function"]["arguments"]

                try:
                    action = parent_session._toolset.parse(func_name, func_args)
                except Exception as exc:
                    subtask_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": f"Error: {exc}",
                        }
                    )
                    continue

                if func_name == "Shell":
                    parts: list[str] = []
                    tr_id = _uuid.uuid4().hex
                    async for chunk_text in parent_session._sandbox.stream_shell(
                        action.command, action.timeout_ms
                    ):
                        parts.append(chunk_text)
                        await channel.chunk(
                            tr_id,
                            "tool_result",
                            chunk_text,
                            chunk_id=tr_id,
                        )
                    exit_code = parent_session._sandbox.terminal._last_exit_code
                    raw = "".join(parts)
                    result = (
                        f"{raw.rstrip()}\n[exit code: {exit_code}]"
                        if exit_code != 0
                        else raw.rstrip() or "(no output)"
                    )
                else:
                    try:
                        result = await action.execute(sandbox=parent_session._sandbox)
                    except Exception as exc:
                        result = f"Error: {exc}"

                subtask_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    }
                )

        return (
            f"SubTask completed. Result: {last_answer}"
            if last_answer
            else "SubTask completed (no output)."
        )

    # ============================================================
    # internal
    # ============================================================

    def _on_done(self, task: asyncio.Task) -> None:
        """query_loop 完成回调（成功或异常）。"""
        self._state = "idle"
        self._loop_task = None
        exc = task.exception()
        if exc:
            import traceback

            traceback.print_exception(type(exc), exc, exc.__traceback__)


# ── helpers ────────────────────────────────────────────────


def _safe_json_loads(s: str) -> dict:
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {}
