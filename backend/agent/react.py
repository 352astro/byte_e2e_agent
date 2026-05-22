# ReAct 智能体 — 核心循环（原生 tool_calls）
import asyncio
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator

from agent.llm import HelloAgentsLLM
from agent.plan_manager import PlanManager
from agent.sandbox import SandBox
from agent.tools.shell import get_platform_hint
from agent.tools.skill import get_skills_summary
from agent.tools.subtask import SubTask
from agent.tools.toolset import ToolSet
from agent.turn import ToolStep, Turn
from agent.utils._term import dim, info, step, success, tool, warn

# ── System prompt（不再注入 JSON schema）──────────────────

SYSTEM_PROMPT = """\
You are an intelligent assistant capable of using external tools and following a plan.
Use the provided functions to interact with the system.

## Rules
- Pick the function that best fits the current situation.
- PlanRewrite — replace the entire plan (CAUTION: discards all progress)
- PlanAdvance — move the current active plan item forward
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
    ) -> None:
        self.llm_client = llm_client
        self._toolset = toolset or _default_toolset()
        self._sandbox = sandbox or SandBox()
        self._system_msg: dict | None = None
        self._messages: list[dict] = []  # OpenAI-format message chain for LLM context
        self._turns: list[Turn] = []  # structured Turn snapshots for frontend history

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
        return [asdict(t) for t in self._turns]

    async def clear(self) -> None:
        self._system_msg = None
        self._messages = []
        self._turns = []
        await self._sandbox.shutdown()

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
            elif kind == "plan_rewrite":
                items = event.get("items", [])
                desc = items[0]["description"] if items else "?"
                print(info(f"[Plan] Rewrite: {len(items)} item(s), first: {desc}"))
            elif kind == "plan_advance":
                print(info(f"[Plan] Advance: {event.get('summary', '?')}"))
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
        plan_manager = PlanManager()
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

        # Record user question in message chain and Turn history
        question_msg = {"role": "user", "content": question}
        self._messages.append(question_msg)
        self._turns.append(Turn(role="user", question=question))

        while current_step < max_steps:
            current_step += 1
            yield {"type": "step_start", "step": current_step}

            # 1. build messages
            step_messages: list[dict] = [
                self._system_msg,
                *self._messages,
            ]
            plan_str = plan_manager.get_plan_string()
            if plan_str != "(No plan yet — consider using PlanRewrite to create one.)":
                step_messages.append(
                    {"role": "user", "content": f"## Current Plan\n{plan_str}"}
                )

            # 2. call LLM
            output = _LLMOutput()
            tools = self._toolset.openai_tools
            async for event in self._stream_llm(step_messages, tools, output):
                yield event

            # 3. build assistant Turn
            assist_turn = Turn(
                role="assistant",
                reasoning=output.reasoning,
                content=output.content,
            )
            self._turns.append(assist_turn)

            # 4. handle finish
            if output.finish_reason == "stop":
                answer = output.content.strip() or "Done."
                self._messages.append({"role": "assistant", "content": answer})
                assist_turn.finish_answer = answer
                yield {"type": "finish", "answer": answer}
                return

            # 5. handle tool_calls
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
            self._messages.append(assistant_msg)

            # 6. execute tools
            for tc in output.tool_calls:
                async for event in self._execute_one_tool(
                    tc, assist_turn, plan_manager
                ):
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
        assist_turn: Turn,
        plan_manager: PlanManager,
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
            self._messages.append(
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
            self._messages.append(
                {"role": "tool", "tool_call_id": tool_call_id, "content": result_str}
            )
            assist_turn.tool_calls.append(
                ToolStep(name=func_name, arguments=tool_params, result=result_str)
            )
            return

        # ── Plan / SubTask / other SandBox tools ────────
        name = action.function_name()

        if name == "PlanRewrite":
            plan_manager.rewrite(action.items)
            self._messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": "plan rewritten",
                }
            )
            yield {
                "type": "plan_rewrite",
                "items": [it.model_dump() for it in action.items],
            }
            assist_turn.tool_calls.append(
                ToolStep(name=func_name, arguments=tool_params, result="plan rewritten")
            )
            return

        if name == "PlanAdvance":
            plan_manager.advance(action.state)
            self._messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": "plan advanced",
                }
            )
            yield {
                "type": "plan_advance",
                "state": action.state,
                "summary": f"item advanced to {action.state}",
            }
            assist_turn.tool_calls.append(
                ToolStep(
                    name=func_name,
                    arguments=tool_params,
                    result=f"item advanced to {action.state}",
                )
            )
            return

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
            )
            sub_result_text = await sub_agent.run(
                question=action.prompt, max_steps=action.max_steps
            )
            self._messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": f"SubTask completed. Result: {sub_result_text}",
                }
            )
            yield {"type": "subtask_end", "result": sub_result_text}
            assist_turn.tool_calls.append(
                ToolStep(
                    name=func_name,
                    arguments=tool_params,
                    result=sub_result_text,
                )
            )
            return

        # Other SandBox tools (Read, Write, Edit, Search, LoadSkill)
        try:
            result_str = await action.execute(sandbox=self._sandbox)
        except Exception as exc:
            result_str = f"Error: {exc}"

        self._messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "content": result_str}
        )
        yield {"type": "tool_result", "result": result_str}
        assist_turn.tool_calls.append(
            ToolStep(name=func_name, arguments=tool_params, result=result_str)
        )


# ── helpers ────────────────────────────────────────────────


def _safe_json_loads(s: str) -> dict:
    import json

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {}
