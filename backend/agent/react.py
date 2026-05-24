# ReAct 智能体 — 核心循环（原生 tool_calls）
import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from agent.llm import HelloAgentsLLM
from agent.sandbox import SandBox
import agent.session_memory as session_memory
from agent.tools.shell import get_platform_hint
from agent.tools.skill import get_skills_summary
from agent.tools.subtask import SubTask
from agent.tools.toolset import ToolSet
from agent.utils._term import dim, info, step, success, tool, warn

# ── System prompt（不再注入 JSON schema）──────────────────

SYSTEM_PROMPT = """\
You are an intelligent assistant capable of using external tools and following a plan.
Use the provided functions to interact with the system.

## Rules
- Pick the function that best fits the current situation.
- SubTask    — delegate to a fresh sub-agent
- Shell / Read / Write / Edit / Search / LoadSkill — executable tools
- {platform_hint}
- {skills_summary}
"""


def _default_toolset() -> ToolSet:
    from agent.tools import get_all_tool_classes as _all

    return ToolSet(_all())


# ── Internal helpers for run_stream ───────────────────────


@dataclass
class _LLMOutput:
    """Accumulated result from a single LLM streaming call."""

    content: str = ""
    reasoning: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str | None = None


# ============================================================
# ReActAgent
# ============================================================


class ReActAgent:
    """ReAct agent with native function calling and per-instance SandBox."""

    def __init__(
        self,
        llm_client: HelloAgentsLLM,
        toolset: ToolSet | None = None,
        sandbox: SandBox | None = None,
        session_id: str | None = None,
        persist_memory: bool = True,
    ) -> None:
        self.llm_client = llm_client
        self._toolset = toolset or _default_toolset()
        self._sandbox = sandbox or SandBox()
        self.session_id = session_id or self._sandbox.session_id
        self._memory_workspace = (
            self._sandbox.workspace if persist_memory and self.session_id else None
        )
        self._system_msg: dict | None = None
        self._messages: list[dict] = []  # OpenAI-format message chain (sole truth)
        self._load_memory()

    @property
    def history(self) -> list[dict]:
        return self._messages

    @history.setter
    async def history(self, value: list) -> None:
        if not value:
            await self.clear()
        else:
            self._messages = value

    def get_history(self) -> list[dict]:
        """Reconstruct Turn-compatible history from _messages.

        The frontend expects a list of Turn-like dicts with:
          role, question, reasoning, content, tool_calls, finish_answer.
        We rebuild these from the OpenAI-format message chain so we
        don't need a separate _turns store.
        """
        result: list[dict] = []

        for msg in self._messages:
            if msg["role"] == "user":
                result.append(
                    {
                        "role": "user",
                        "question": msg.get("content", ""),
                        "reasoning": "",
                        "content": "",
                        "tool_calls": [],
                        "finish_answer": None,
                    }
                )

            elif msg["role"] == "assistant":
                tool_calls: list[dict] = []
                for tc in msg.get("tool_calls", []):
                    tool_calls.append(
                        {
                            "name": tc["function"]["name"],
                            "arguments": _safe_json_loads(
                                tc["function"].get("arguments", "{}")
                            ),
                            "result": None,  # filled by following tool messages
                            "_tc_id": tc.get("id", ""),  # internal: for result matching
                        }
                    )

                turn: dict = {
                    "role": "assistant",
                    "question": "",
                    "reasoning": msg.get("reasoning_content", ""),
                    "content": msg.get("content") or "",
                    "tool_calls": tool_calls,
                    "finish_answer": None,
                }

                if not tool_calls and msg.get("content"):
                    turn["finish_answer"] = msg["content"]

                result.append(turn)

            elif msg["role"] == "tool":
                tc_id = msg.get("tool_call_id", "")
                # Walk backwards to find the matching tool_call
                for turn in reversed(result):
                    if turn["role"] != "assistant":
                        continue
                    for tc in turn["tool_calls"]:
                        if tc.get("_tc_id") == tc_id:
                            tc["result"] = msg.get("content", "")
                            break
                    break

        # Strip internal _tc_id before returning
        for turn in result:
            for tc in turn.get("tool_calls", []):
                tc.pop("_tc_id", None)

        return result

    async def clear(self) -> None:
        self._system_msg = None
        self._messages = []
        await self._sandbox.shutdown()

    def _load_memory(self) -> None:
        """Load persisted context when this agent is bound to a session."""
        if self._memory_workspace is None:
            return
        self._messages = session_memory.load_memory(
            self._memory_workspace,
            self.session_id,
        )

    async def _record_message(self, message: dict) -> None:
        self._messages.append(message)
        if self._memory_workspace is not None:
            await session_memory.save_memory(
                self._memory_workspace,
                self.session_id,
                message,
            )

    # ── CLI loop ─────────────────────────────────────────

    async def run(self, question: str, max_steps: int = 10) -> str:
        answer: str | None = None
        in_reasoning = False

        async for event in self.run_stream(question, max_steps):
            kind = event["type"]
            if kind == "step_start":
                print(step(f"--- Step {event['step']} ---"))
            elif kind == "reasoning_token":
                if not in_reasoning:
                    print(dim("  [Deep Think]"))
                    in_reasoning = True
                print(dim(event["token"]), end="", flush=True)
            elif kind == "thought_token":
                if in_reasoning:
                    print()
                    in_reasoning = False
                print(event["token"], end="", flush=True)
            elif kind == "thought_end":
                print()
            elif kind == "tool_call":
                print(f"{tool('[Tool]')} {event['tool']}")
            elif kind == "terminal_chunk":
                print(event["chunk"], end="", flush=True)
            elif kind == "tool_result":
                print(event["result"])
            elif kind == "subtask_start":
                print(info(f"[SubTask] launching: {event['prompt'][:80]}..."))
            elif kind == "subtask_end":
                print(info(f"[SubTask] result: {event.get('result', '')[:120]}..."))
            elif kind == "finish":
                answer = event["answer"]
                if answer == "Maximum steps reached; could not produce a final answer.":
                    print(warn(answer))
                else:
                    print(f"{success('[Done]')} {answer}")
                if in_reasoning:
                    print()
                    in_reasoning = False
            elif kind == "error":
                print(warn(event["message"]))

        return answer or "Maximum steps reached; could not produce a final answer."

    # ── Streaming loop ──────────────────────────────────

    async def run_stream(
        self, question: str, max_steps: int = 10
    ) -> AsyncIterator[dict[str, Any]]:
        current_step = 0

        # init system message once
        if self._system_msg is None:
            self._system_msg = {
                "role": "system",
                "content": SYSTEM_PROMPT.format(
                    platform_hint=get_platform_hint(),
                    skills_summary=get_skills_summary(),
                ),
            }

        # Record user question in message chain
        question_msg = {"role": "user", "content": question}
        await self._record_message(question_msg)

        while current_step < max_steps:
            current_step += 1
            yield {"type": "step_start", "step": current_step}

            # 1. build messages
            step_messages: list[dict] = [
                self._system_msg,
                *self._messages,
            ]

            # 2. call LLM
            output = _LLMOutput()
            tools = self._toolset.openai_tools
            async for event in self._stream_llm(step_messages, tools, output):
                yield event

            # 3. handle finish
            if output.finish_reason == "stop":
                answer = output.content.strip() or "Done."
                await self._record_message({"role": "assistant", "content": answer})
                yield {"type": "finish", "answer": answer}
                return

            # 4. handle tool_calls
            if not output.tool_calls:
                yield {
                    "type": "error",
                    "message": "LLM returned no tool_calls and no content.",
                }
                break

            # Build assistant message for LLM context
            assistant_msg: dict = {
                "role": "assistant",
                "content": output.content or None,
                "tool_calls": output.tool_calls,
            }
            if output.reasoning:
                assistant_msg["reasoning_content"] = output.reasoning
            await self._record_message(assistant_msg)

            # 5. execute tools
            for tc in output.tool_calls:
                async for event in self._execute_one_tool(tc):
                    yield event

        yield {
            "type": "finish",
            "answer": "Maximum steps reached; could not produce a final answer.",
        }

    # ── LLM streaming ────────────────────────────────────

    async def _stream_llm(
        self,
        messages: list[dict],
        tools: list[dict],
        output: _LLMOutput,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream LLM response, yield frontend events and populate output."""
        async for ev in self.llm_client.think_stream(messages=messages, tools=tools):
            if ev["kind"] == "reasoning":
                yield {"type": "reasoning_token", "token": ev["token"]}
                output.reasoning += ev["token"]
            elif ev["kind"] == "content":
                yield {"type": "thought_token", "token": ev["token"]}
                output.content += ev["token"]
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
                    output.tool_calls[idx]["function"]["arguments"] += fn["arguments"]
                yield {
                    "type": "tool_call_stream",
                    "index": idx,
                    "name": fn.get("name") or None,
                    "args_len": len(fn.get("arguments", "")),
                }
            elif ev["kind"] == "finish_reason":
                output.finish_reason = ev["finish_reason"]

        yield {"type": "thought_end"}

    # ── Tool execution ───────────────────────────────────

    async def _execute_one_tool(
        self,
        tc: dict,
    ) -> AsyncIterator[dict[str, Any]]:
        """Parse and execute a single tool call. Yields frontend events."""
        func_name: str = tc["function"]["name"]
        func_args: str = tc["function"]["arguments"]
        tool_call_id: str = tc["id"]
        tool_params = _safe_json_loads(func_args)

        # Emit tool_call event
        yield {
            "type": "tool_call",
            "tool": func_name,
            "params": tool_params,
        }

        # Parse into Pydantic model
        try:
            action = self._toolset.parse(func_name, func_args)
        except Exception as exc:
            result = f"Error parsing {func_name}: {exc}"
            await self._record_message(
                {"role": "tool", "tool_call_id": tool_call_id, "content": result}
            )
            yield {"type": "tool_result", "result": result}
            return

        # ── Shell: streaming ──────────────────────────
        if func_name == "Shell":
            output_parts: list[str] = []
            async for chunk in self._sandbox.stream_shell(
                action.command, action.timeout_ms
            ):
                output_parts.append(chunk)
                yield {"type": "terminal_chunk", "chunk": chunk}
            exit_code = self._sandbox.terminal._last_exit_code
            raw = "".join(output_parts)
            result_str = (
                f"{raw.rstrip()}\n[exit code: {exit_code}]"
                if exit_code != 0
                else raw.rstrip() or "(no output)"
            )
            await self._record_message(
                {"role": "tool", "tool_call_id": tool_call_id, "content": result_str}
            )
            return

        # ── SubTask / other SandBox tools ───────────────
        name = action.function_name()

        if name == "SubTask":
            yield {
                "type": "subtask_start",
                "prompt": action.prompt,
                "max_steps": action.max_steps,
            }
            sub_agent = ReActAgent(
                self.llm_client,
                toolset=self._toolset.without(SubTask),
                sandbox=self._sandbox,
                persist_memory=False,
            )
            sub_result_text = await sub_agent.run(
                question=action.prompt, max_steps=action.max_steps
            )
            await self._record_message(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": f"SubTask completed. Result: {sub_result_text}",
                }
            )
            yield {"type": "subtask_end", "result": sub_result_text}
            return

        # Other SandBox tools (Read, Write, Edit, Search, LoadSkill)
        try:
            result_str = await action.execute(sandbox=self._sandbox)
        except Exception as exc:
            result_str = f"Error: {exc}"

        await self._record_message(
            {"role": "tool", "tool_call_id": tool_call_id, "content": result_str}
        )
        yield {"type": "tool_result", "result": result_str}


# ── helpers ────────────────────────────────────────────────


def _safe_json_loads(s: str) -> dict:
    import json

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {}
