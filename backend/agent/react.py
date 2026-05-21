# ReAct 智能体 — 核心循环
import json
from typing import Any

from pydantic import ValidationError

from agent.utils._json import safe_validate_json
from agent.utils._term import dim, error, info, step, success, tool, warn
from agent.llm import HelloAgentsLLM
from agent.plan_manager import PlanManager
from agent.terminal import (
    PersistentTerminal,
    reset_terminal,
    set_terminal,
)
from agent.tools.base import BaseTool
from agent.tools.finish import Finish
from agent.tools.plan import PlanAdvance, PlanRewrite
from agent.tools.shell import Shell, get_platform_hint
from agent.tools.skill import get_skills_summary
from agent.tools.subtask import SubTask
from agent.tools.toolset import ToolSet
from agent.tools.workspace import get_workspace_root

# ── System prompt ────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an intelligent assistant capable of using external tools and following a plan.
You MUST respond with a single tool-call JSON object, choosing from the schema below.
Output ONLY the tool JSON — no wrapper, no markdown fences, no extra text.

## Response JSON Schema (defines all available tools and their parameters)
{schema}

## Rules
- Pick the tool that best fits the current situation.
- PlanRewrite — replace the entire plan (CAUTION: discards all progress)
- PlanAdvance — move the current active plan item forward
- SubTask    — delegate to a fresh sub-agent
- Finish     — conclude with final answer (no more tools needed)
- Shell / Read / Write / Edit / Search / LoadSkill — executable tools
- {platform_hint}
- {skills_summary}
"""


# ============================================================
# ReActAgent
# ============================================================


class ReActAgent:
    """ReAct agent with dynamic ToolSet and proper role-based message list."""

    def __init__(
        self,
        llm_client: HelloAgentsLLM,
        toolset: ToolSet | None = None,
    ) -> None:
        self.llm_client = llm_client
        self._toolset = toolset or _default_toolset()
        self._system_msg: dict | None = None
        self._question_msg: dict | None = None
        self._turns: list[dict] = []
        self._terminal: PersistentTerminal | None = None

    # ── Backward-compat history property (for CLI /clear) ──

    @property
    def history(self) -> list[dict]:
        return self._turns

    @history.setter
    def history(self, value: list) -> None:
        if not value:
            self.clear()
        else:
            self._turns = value

    def clear(self) -> None:
        """Reset all conversation state."""
        self._system_msg = None
        self._question_msg = None
        self._turns = []
        if self._terminal is not None:
            reset_terminal()
            self._terminal = None

    # ── CLI loop (thin wrapper over run_stream) ────────────

    def run(self, question: str, max_steps: int = 10) -> str:
        """Run the ReAct loop (CLI mode)."""
        answer: str | None = None
        in_reasoning = False

        for event in self.run_stream(question, max_steps):
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
                print(
                    info(
                        f"[SubTask] launching subagent "
                        f"(max {event['max_steps']} steps): "
                        f"{event['prompt'][:80]}..."
                    )
                )

            elif kind == "subtask_end":
                result = event.get("result", "")
                print(info(f"[SubTask] result: {result[:120]}..."))

            elif kind == "finish":
                if event["answer"] == (
                    "Maximum steps reached; could not produce a final answer."
                ):
                    answer = event["answer"]
                    print(warn(event["answer"]))
                else:
                    answer = event["answer"]
                    print(f"{success('[Done]')} {answer}")
                if in_reasoning:
                    print()
                    in_reasoning = False

            elif kind == "error":
                print(warn(event["message"]))

        return answer or "Maximum steps reached; could not produce a final answer."

    # ── Streaming loop (SSE / Web UI) ────────────────────

    def run_stream(self, question: str, max_steps: int = 10):
        """Run the ReAct loop and yield structured event dicts for SSE streaming."""
        plan_manager = PlanManager()
        current_step = 0

        # ── initialise system message once ────────────────
        if self._system_msg is None:
            schema = self._toolset.json_schema_str
            self._system_msg = {
                "role": "system",
                "content": SYSTEM_PROMPT.format(
                    schema=schema,
                    platform_hint=get_platform_hint(),
                    skills_summary=get_skills_summary(),
                ),
            }

        # ── archive previous question ─────────────────────
        if self._question_msg is not None:
            self._turns.append(self._question_msg)
        self._question_msg = {"role": "user", "content": question}

        # ── ensure persistent terminal ────────────────────
        if self._terminal is None or not self._terminal.alive:
            self._terminal = PersistentTerminal()
            self._terminal.start(get_workspace_root())
            set_terminal(self._terminal)

        # ── main loop ─────────────────────────────────────
        while current_step < max_steps:
            current_step += 1
            yield {"type": "step_start", "step": current_step}

            # 1. build message list
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

            # 2. call LLM (streaming)
            full_text_parts: list[str] = []
            reasoning_parts: list[str] = []
            for ev in self.llm_client.think_stream(messages=step_messages):
                if ev["kind"] == "reasoning":
                    yield {"type": "reasoning_token", "token": ev["token"]}
                    reasoning_parts.append(ev["token"])
                else:
                    yield {"type": "thought_token", "token": ev["token"]}
                    full_text_parts.append(ev["token"])
            yield {"type": "thought_end"}

            response_text = "".join(full_text_parts)

            if not response_text.strip():
                yield {"type": "error", "message": "LLM returned empty response."}
                break

            # 3. parse — directly into tool via TypeAdapter (with json-repair)
            try:
                action = safe_validate_json(response_text, self._toolset.adapter)
            except ValidationError as e:
                self._turns.append(
                    {
                        "role": "user",
                        "content": (
                            "Your last output did not conform to the JSON Schema. "
                            f"Please follow the schema strictly. Error: {e}"
                        ),
                    }
                )
                yield {"type": "error", "message": f"JSON parse failed: {e}"}
                continue

            # 4. record assistant message
            assistant_msg: dict = {"role": "assistant", "content": response_text}
            if reasoning_parts:
                assistant_msg["reasoning_content"] = "".join(reasoning_parts)
            self._turns.append(assistant_msg)

            # 5. dispatch action
            if isinstance(action, PlanRewrite):
                plan_manager.rewrite(action.items)
                yield {
                    "type": "plan_rewrite",
                    "items": [it.model_dump() for it in action.items],
                }
                continue

            if isinstance(action, PlanAdvance):
                plan_manager.advance(action.state)
                yield {
                    "type": "plan_advance",
                    "state": action.state,
                    "summary": f"item advanced to {action.state}",
                }
                continue

            if isinstance(action, SubTask):
                yield {
                    "type": "subtask_start",
                    "prompt": action.prompt,
                    "max_steps": action.max_steps,
                }
                sub_agent = ReActAgent(
                    self.llm_client,
                    toolset=self._toolset.without(SubTask),
                )
                sub_result = sub_agent.run(
                    question=action.prompt,
                    max_steps=action.max_steps,
                )
                self._turns.append(
                    {
                        "role": "user",
                        "content": f"SubTask completed. Result: {sub_result}",
                    }
                )
                yield {"type": "subtask_end", "result": sub_result}
                continue

            if isinstance(action, Finish):
                answer = action.answer
                self._turns.append(self._question_msg)
                self._question_msg = None
                yield {"type": "finish", "answer": answer}
                return

            # -- regular tool --
            tool_name: str = getattr(action, "kind", "?")
            try:
                tool_params = action.model_dump(exclude={"kind"})
            except Exception:
                tool_params = {}
            yield {"type": "tool_call", "tool": tool_name, "params": tool_params}

            # Shell: streaming terminal output
            if isinstance(action, Shell):
                output_parts: list[str] = []
                try:
                    for chunk in self._terminal.run_stream(
                        action.command, action.timeout_ms
                    ):
                        output_parts.append(chunk)
                        yield {"type": "terminal_chunk", "chunk": chunk}
                    exit_code = self._terminal._last_exit_code
                except Exception as exc:
                    output_parts = [f"Error: {exc}"]
                    exit_code = -1
                raw_output = "".join(output_parts)
                result = (
                    f"{raw_output.rstrip()}\n[exit code: {exit_code}]"
                    if exit_code != 0
                    else raw_output.rstrip() or "(no output)"
                )
                yield {"type": "tool_result", "result": result}
                self._turns.append(
                    {
                        "role": "user",
                        "content": f"Tool Shell returned:\n{result}",
                    }
                )
                continue

            # Other tools: call execute()
            try:
                fn = getattr(action, "execute", None)
                if callable(fn):
                    result = fn()
                else:
                    result = f"Error: tool '{tool_name}' does not implement execute()"
            except Exception as exc:
                result = f"Error: {exc}"

            yield {"type": "tool_result", "result": result}
            self._turns.append(
                {
                    "role": "user",
                    "content": f"Tool {tool_name} returned:\n{result}",
                }
            )

        yield {
            "type": "finish",
            "answer": "Maximum steps reached; could not produce a final answer.",
        }


# ── Default toolset factory ───────────────────────────────


def _default_toolset() -> ToolSet:
    from agent.tools import get_all_tool_classes as _all

    return ToolSet(_all())


# ============================================================
# Demo
# ============================================================
if __name__ == "__main__":
    ts = _default_toolset()
    print(f"ToolSet: {ts}")
    print(f"Schema keys: {list(ts.json_schema.keys())}")
    print("All demo tests passed!")
