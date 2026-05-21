# ReAct 提示词模板
import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from agent._json import safe_parse_json
from agent._term import dim, error, info, step, success, tool, warn
from agent.llm import HelloAgentsLLM
from agent.plan_manager import PlanManager
from agent.terminal import (
    PersistentTerminal,
    reset_terminal,
    set_terminal,
)
from agent.tools import Finish, SubTool, Tool, get_sub_tool_classes
from agent.tools.shell import Shell, get_platform_hint
from agent.tools.workspace import get_workspace_root
from agent.tools.plan import PlanAdvance, PlanRewrite
from agent.tools.subtask import SubTask

# ============================================================
# ReAct response models
# ============================================================


class Response(BaseModel):
    """Top-level agent response: action accepts all tools (including SubTask)."""

    thought: str = Field(..., description="Your reasoning and decision-making process")
    action: Tool = Field(
        ...,
        description=(
            "The action to take. Output a tool JSON object directly; "
            "the 'kind' field determines which tool is dispatched."
        ),
    )


class SubResponse(BaseModel):
    """Sub-agent response: action accepts restricted tools (no SubTask recursion)."""

    thought: str = Field(..., description="Your reasoning and decision-making process")
    action: SubTool = Field(
        ...,
        description=(
            "The action to take. Output a tool JSON object directly; "
            "the 'kind' field determines which tool is dispatched."
        ),
    )


# ── System prompt (static, cached per schema version) ──────

SYSTEM_PROMPT = """\
You are an intelligent assistant capable of using external tools and following a plan.
You MUST respond with valid JSON only, strictly following the schema below.

## Response JSON Schema (defines all available tools and their parameters)
{schema}

## Rules
- thought: your analysis, reasoning, and decision-making process (string)
- action: the tool invocation JSON object, discriminated by "kind"
  * PlanRewrite — replace the entire plan (CAUTION: discards all progress)
  * PlanAdvance — move the current active plan item forward
  * SubTask    — delegate a complex sub-task to a fresh sub-agent
  * Finish     — conclude with a final answer (no more tools needed)
  * Shell / Read / Write / Edit / Search — executable tools
- {platform_hint}
- Every response MUST include both "thought" and "action" fields.
- {platform_hint}
"""


# ============================================================
# ReActAgent
# ============================================================


class ReActAgent:
    """ReAct agent with built-in PlanManager and configurable tool set.

    Maintains a proper role-based message list (system → user → assistant → user …)
    instead of cramming everything into a single user message.
    """

    def __init__(self, llm_client: HelloAgentsLLM) -> None:
        self.llm_client = llm_client
        self._system_msg: dict | None = None  # cached system message
        self._question_msg: dict | None = None  # current user question
        self._turns: list[dict] = []  # past assistant + user(tool) msgs
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
        """Reset all conversation state (called by CLI /clear)."""
        self._system_msg = None
        self._question_msg = None
        self._turns = []
        if self._terminal is not None:
            reset_terminal()
            self._terminal = None

    # ── CLI loop (thin wrapper over run_stream) ────────────

    def run(
        self,
        question: str,
        max_steps: int = 10,
        *,
        response_cls: Any = Response,
        tool_classes: Any = None,
    ) -> str:
        """Run the ReAct loop (CLI mode).

        Thin wrapper around run_stream() — consumes structured events
        and formats them for the terminal with ANSI colours.
        """
        answer: str | None = None
        in_reasoning = False

        for event in self.run_stream(
            question,
            max_steps,
            response_cls=response_cls,
            tool_classes=tool_classes,
        ):
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

    def run_stream(
        self,
        question: str,
        max_steps: int = 10,
        *,
        response_cls: Any = Response,
        tool_classes: Any = None,
    ):
        """Run the ReAct loop and yield structured event dicts for SSE streaming.

        Builds a proper role-based message list:
            system (instructions + schema)
            user   (question)
            … alternating assistant (JSON response) / user (tool result) …

        Event types (same as before):
            step_start, reasoning_token, thought_token, thought_end,
            tool_call, tool_result, plan_rewrite, plan_advance,
            subtask_start, subtask_end, finish, error
        """
        if tool_classes is None:
            from agent.tools import get_all_tool_classes as _all

            tool_classes = _all()

        plan_manager = PlanManager()
        current_step = 0

        response_schema = json.dumps(
            response_cls.model_json_schema(), indent=2, ensure_ascii=False
        )

        # ── initialise system message once ────────────────
        if self._system_msg is None:
            self._system_msg = {
                "role": "system",
                "content": SYSTEM_PROMPT.format(schema=response_schema, platform_hint=get_platform_hint()),
            }

        # ── archive previous question (multi-turn support) ─
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

            # 1. build message list for this step
            step_messages: list[dict] = [
                self._system_msg,
                self._question_msg,
                *self._turns,
            ]

            # inject current plan as ephemeral user message
            plan_str = plan_manager.get_plan_string()
            if plan_str != "(No plan yet — consider using PlanRewrite to create one.)":
                step_messages.append(
                    {"role": "user", "content": f"## Current Plan\n{plan_str}"}
                )

            # 2. call LLM (streaming) — split reasoning from content
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

            # 3. parse response (with json-repair fallback)
            try:
                response = safe_parse_json(response_text, response_cls)
            except ValidationError as e:
                # both direct parse and repair failed —
                # feed parse error back as a user message
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

            # 4. record assistant message (with reasoning if DeepSeek thinking is on)
            assistant_msg: dict = {"role": "assistant", "content": response_text}
            if reasoning_parts:
                assistant_msg["reasoning_content"] = "".join(reasoning_parts)
            self._turns.append(assistant_msg)

            # 5. dispatch action
            action = response.action

            # -- Plan --
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

            # -- SubTask --
            if isinstance(action, SubTask):
                yield {
                    "type": "subtask_start",
                    "prompt": action.prompt,
                    "max_steps": action.max_steps,
                }
                sub_agent = ReActAgent(self.llm_client)
                sub_result = sub_agent.run(
                    question=action.prompt,
                    max_steps=action.max_steps,
                    response_cls=SubResponse,
                    tool_classes=get_sub_tool_classes(),
                )
                # record sub-task as a user message
                self._turns.append(
                    {
                        "role": "user",
                        "content": f"SubTask completed. Result: {sub_result}",
                    }
                )
                yield {"type": "subtask_end", "result": sub_result}
                continue

            # -- Finish --
            if isinstance(action, Finish):
                answer = action.answer
                # archive Q&A into turns so multi-turn context carries over
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

            # ── Bash: streaming terminal output ──────
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
                if exit_code != 0:
                    result = f"{raw_output.rstrip()}\n[exit code: {exit_code}]"
                else:
                    result = raw_output.rstrip() if raw_output.strip() else "(no output)"
                yield {"type": "tool_result", "result": result}
                self._turns.append(
                    {"role": "user", "content": f"Tool Shell returned:\n{result}"},
                )
                continue

            # ── other tools ──────────────────────────
            try:
                fn = getattr(action, "execute", None)
                if callable(fn):
                    result = fn()
                else:
                    result = f"Error: tool '{tool_name}' does not implement execute()"
            except Exception as exc:
                result = f"Error: {exc}"

            yield {"type": "tool_result", "result": result}

            # record tool result as a user message
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


# ============================================================
# Demo
# ============================================================
if __name__ == "__main__":
    r1 = Response(thought="Done.", action=Finish(answer="Hello, world!"))
    print("========== Response (Finish) ==========")
    print("model_dump_json:", r1.model_dump_json(indent=2))

    r2 = Response(
        thought="Too complex; delegate to subagent.",
        action=SubTask(prompt="Analyze the data", max_steps=3),
    )
    print("\n========== Response (SubTask) ==========")
    print("model_dump_json:", r2.model_dump_json(indent=2))

    print("\n========== SubResponse rejects SubTask ==========")
    try:
        SubResponse.model_validate_json(
            '{"thought": "t", "action": {"kind": "SubTask", "prompt": "x"}}'
        )
        print("ERROR: should have rejected SubTask in SubResponse")
    except ValidationError:
        print("Correctly rejected: SubTask not in SubTool union")

    sr = SubResponse.model_validate_json(
        '{"thought": "need info", "action": {"kind": "Search", "query": "weather"}}'
    )
    print(f"\nSubResponse accepted Search: {type(sr.action).__name__}")

    print("\nAll demo tests passed!")
