# ReAct 智能体 — 核心循环（原生 tool_calls）
import asyncio
from typing import Any, AsyncIterator

from agent.llm import HelloAgentsLLM
from agent.plan_manager import PlanManager
from agent.sandbox import SandBox
from agent.tools.shell import Shell, get_platform_hint
from agent.tools.skill import get_skills_summary
from agent.tools.subtask import SubTask
from agent.tools.toolset import ToolSet
from agent.turn import ToolStep, Turn
from agent.utils._term import dim, error, info, step, success, tool, warn

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
        self._question_msg: dict | None = None
        self._turns: list[dict] = []
        self._turns_history: list[Turn] = []

    @property
    def history(self) -> list[dict]:
        return self._turns

    @history.setter
    async def history(self, value: list) -> None:
        if not value:
            await self.clear()
        else:
            self._turns = value

    def get_history(self) -> list[dict]:
        return [_turn_to_dict(t) for t in self._turns_history]

    async def clear(self) -> None:
        self._system_msg = None
        self._question_msg = None
        self._turns = []
        self._turns_history = []
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

        # archive previous question
        if self._question_msg is not None:
            self._turns.append(self._question_msg)
        self._question_msg = {"role": "user", "content": question}
        self._turns_history.append(Turn(role="user", question=question))

        while current_step < max_steps:
            current_step += 1
            yield {"type": "step_start", "step": current_step}

            # 1. build messages
            step_messages: list[dict] = [
                self._system_msg,
                self._question_msg,
                *self._turns,
            ]
            plan_str = plan_manager.get_plan_string()
            if plan_str != "(No plan yet — consider using PlanRewrite to create one.)":
                step_messages.append(
                    {"role": "user", "content": f"## Current Plan\n{plan_str}"}
                )

            # 2. call LLM with native tools
            tools = self._toolset.openai_tools
            content_parts: list[str] = []
            reasoning_parts: list[str] = []
            tool_calls_raw: list[dict] = []
            finish_reason: str | None = None

            async for ev in self.llm_client.think_stream(
                messages=step_messages, tools=tools
            ):
                if ev["kind"] == "reasoning":
                    yield {"type": "reasoning_token", "token": ev["token"]}
                    reasoning_parts.append(ev["token"])
                elif ev["kind"] == "content":
                    yield {"type": "thought_token", "token": ev["token"]}
                    content_parts.append(ev["token"])
                elif ev["kind"] == "tool_call_chunk":
                    tc = ev["tool_call"]
                    # Accumulate tool call chunks
                    idx = tc.get("index", 0)
                    while len(tool_calls_raw) <= idx:
                        tool_calls_raw.append(
                            {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        )
                    if tc.get("id"):
                        tool_calls_raw[idx]["id"] = tc["id"]
                    if tc.get("function", {}).get("name"):
                        tool_calls_raw[idx]["function"]["name"] += tc["function"][
                            "name"
                        ]
                    if tc.get("function", {}).get("arguments"):
                        tool_calls_raw[idx]["function"]["arguments"] += tc["function"][
                            "arguments"
                        ]
                    # Stream progress to frontend
                    yield {
                        "type": "tool_call_stream",
                        "index": idx,
                        "name": tc.get("function", {}).get("name") or None,
                        "args_len": len(tc.get("function", {}).get("arguments", "")),
                    }
                elif ev["kind"] == "finish_reason":
                    finish_reason = ev["finish_reason"]

            yield {"type": "thought_end"}
            content_text = "".join(content_parts)

            # 3. build assistant Turn (before dispatch, so it exists for both stop and tool_calls)
            assist_turn = Turn(
                role="assistant",
                reasoning="".join(reasoning_parts),
                content=content_text,
            )
            self._turns_history.append(assist_turn)

            # 4. handle finish
            if finish_reason == "stop":
                answer = content_text.strip() or "Done."
                self._turns.append(self._question_msg)
                self._question_msg = None
                assist_turn.finish_answer = answer
                yield {"type": "finish", "answer": answer}
                return

            # 5. handle tool_calls
            if not tool_calls_raw:
                yield {
                    "type": "error",
                    "message": "LLM returned no tool_calls and no content.",
                }
                break

            # Build assistant message with tool_calls
            assistant_msg: dict = {
                "role": "assistant",
                "content": content_text or None,
                "tool_calls": tool_calls_raw,
            }
            if reasoning_parts:
                assistant_msg["reasoning_content"] = "".join(reasoning_parts)
            self._turns.append(assistant_msg)

            # 5. dispatch each tool call
            for tc in tool_calls_raw:
                func_name = tc["function"]["name"]
                func_args = tc["function"]["arguments"]
                tool_call_id = tc["id"]
                tool_params = _safe_json_loads(func_args)

                # Emit tool_call event (with kind for frontend)
                kind_val = _get_kind(func_name)
                yield {
                    "type": "tool_call",
                    "tool": kind_val or func_name,
                    "params": tool_params,
                }

                # Parse into Pydantic model
                try:
                    action = self._toolset.parse(func_name, func_args)
                except Exception as exc:
                    result = f"Error parsing {func_name}: {exc}"
                    self._turns.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": result,
                        }
                    )
                    yield {"type": "tool_result", "result": result}
                    continue

                # ── Dispatch by type ──────────────────
                if func_name == "Shell":
                    # Shell streaming: yield terminal_chunk events inline
                    output_parts = []
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
                    self._turns.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": result_str,
                        }
                    )
                    assist_turn.tool_calls.append(
                        ToolStep(
                            name=func_name, arguments=tool_params, result=result_str
                        )
                    )
                    continue

                result_event, should_return = await self._dispatch(
                    action, tool_call_id, plan_manager, question
                )
                if result_event is not None:
                    yield result_event
                    # Record tool result in Turn
                    if result_event.get("type") == "tool_result":
                        assist_turn.tool_calls.append(
                            ToolStep(
                                name=func_name,
                                arguments=tool_params,
                                result=result_event["result"],
                            )
                        )
                if should_return:
                    return

        yield {
            "type": "finish",
            "answer": "Maximum steps reached; could not produce a final answer.",
        }

    # ── Tool dispatch ────────────────────────────────────

    async def _dispatch(self, action, tool_call_id, plan_manager, question):
        """Return (extra_event | None, should_return_bool)."""
        name = action.function_name()

        # Plan
        if name == "PlanRewrite":
            plan_manager.rewrite(action.items)
            self._turns.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": "plan rewritten",
                }
            )
            return (
                {
                    "type": "plan_rewrite",
                    "items": [it.model_dump() for it in action.items],
                },
                False,
            )

        if name == "PlanAdvance":
            plan_manager.advance(action.state)
            self._turns.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": "plan advanced",
                }
            )
            return (
                {
                    "type": "plan_advance",
                    "state": action.state,
                    "summary": f"item advanced to {action.state}",
                },
                False,
            )

        # SubTask
        if name == "SubTask":
            yield_event = {
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
            self._turns.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": f"SubTask completed. Result: {sub_result_text}",
                }
            )
            return (
                {"type": "subtask_end", "result": sub_result_text},
                False,
            )

        # Shell: streaming — handle inline for terminal_chunk events
        if name == "Shell":
            return ("__SHELL_STREAMING__", False)

        # Other SandBox tools
        try:
            result_str = await action.execute(sandbox=self._sandbox)
        except Exception as exc:
            result_str = f"Error: {exc}"

        self._turns.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result_str,
            }
        )
        return ({"type": "tool_result", "result": result_str}, False)


# ── helpers ────────────────────────────────────────────────


def _safe_json_loads(s: str) -> dict:
    import json

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {}


def _get_kind(func_name: str) -> str:
    """Map function name back to kind string if different."""
    return func_name  # our function names ARE the kind values


def _turn_to_dict(t: Turn) -> dict:
    return {
        "role": t.role,
        "question": t.question,
        "reasoning": t.reasoning,
        "content": t.content,
        "tool_calls": [
            {"name": ts.name, "arguments": ts.arguments, "result": ts.result}
            for ts in t.tool_calls
        ],
        "finish_answer": t.finish_answer,
    }
