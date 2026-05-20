# ReAct 提示词模板
import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from agent._term import error, info, step, success, tool, warn
from agent.llm import HelloAgentsLLM
from agent.plan_manager import PlanManager
from agent.tools import Finish, SubTool, Tool, get_sub_tool_classes
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


# ── Prompt template (cache-friendly paragraph order) ────────
#
#   1. static (system / schema)   - cached forever
#   2. stable (question)          - per-run static, establishes task
#   3. high-churn (history)       - appended every step
#   4. low-churn  (plan)          - changes on auto-advance, tiny, last = zero tail cost

REACT_PROMPT_TEMPLATE = """
You are an intelligent assistant capable of using external tools and following a plan.
You MUST respond with valid JSON only, strictly following the schema below.

## Response JSON Schema (defines all available tools and their parameters)
{response_schema}

Field descriptions:
- thought: your analysis, reasoning, and decision-making process (string)
- action: the tool invocation. Output the tool's JSON object directly.
  Tools are discriminated by the "kind" field; all available tools are
  enumerated in the schema above (see the action field's anyOf).
  * Use PlanRewrite to replace the ENTIRE plan (CAUTION: discards all progress).
  * Use PlanAdvance to move the current active item forward.
  * Use SubTask (if available) to delegate a complex sub-task to a fresh sub-agent.
  * Use Finish to conclude with a final answer.
  * Every tool call MUST include the correct "kind" field.

## Current Question
Question: {question}

## History
{history}

## Current Plan
{plan}
"""


# ============================================================
# ReActAgent
# ============================================================


class ReActAgent:
    """ReAct agent with built-in PlanManager and configurable tool set."""

    def __init__(self, llm_client: HelloAgentsLLM) -> None:
        self.llm_client = llm_client
        self.history: list[str] = []

    # ── main loop ────────────────────────────────────────

    def run(
        self,
        question: str,
        max_steps: int = 10,
        *,
        response_cls: Any = Response,
        tool_classes: Any = None,
    ) -> str:
        """Run the ReAct loop.

        Args:
            question:      user question
            max_steps:     max reasoning steps
            response_cls:  Pydantic model for validating LLM output
                           (Response=all tools, SubResponse=restricted)
            tool_classes:  available tool classes; None = all top-level tools
        """
        if tool_classes is None:
            from agent.tools import get_all_tool_classes as _all

            tool_classes = _all()

        plan_manager = PlanManager()
        current_step = 0

        # pre-generate response schema (tool info included)
        response_schema = json.dumps(
            response_cls.model_json_schema(), indent=2, ensure_ascii=False
        )

        while current_step < max_steps:
            current_step += 1
            print(step(f"--- Step {current_step} ---"))

            # 1. format prompt
            history_str = "\n".join(self.history) if self.history else "(None)"
            plan_str = plan_manager.get_plan_string()
            prompt = REACT_PROMPT_TEMPLATE.format(
                response_schema=response_schema,
                question=question,
                history=history_str,
                plan=plan_str,
            )

            # 2. call LLM
            messages = [{"role": "user", "content": prompt}]
            response_text = self.llm_client.think(messages=messages)

            if not response_text:
                print(error("LLM returned empty response."))
                break

            # 3. parse response
            try:
                response = response_cls.model_validate_json(response_text)
            except ValidationError as e:
                print(warn("JSON parse failed; feeding error back to LLM."))
                self.history.append(
                    f"System: Your last output did not conform to the JSON Schema. "
                    f"Please follow the schema strictly. Error details: {e}"
                )
                continue

            # 4. record thought
            self.history.append(f"Thought: {response.thought}")

            # 5. dispatch action
            action = response.action

            # -- 5a. Plan --
            if isinstance(action, PlanRewrite):
                result = plan_manager.rewrite(action.items)
                print(info(f"[Plan] Rewrite: {result.split(chr(10))[0]}"))
                self.history.append(f"Plan: {result}")
                continue

            if isinstance(action, PlanAdvance):
                result = plan_manager.advance(action.state)
                print(info(f"[Plan] Advance: {result}"))
                self.history.append(f"Plan: {result}")
                continue

            # -- 5b. SubTask sub-agent --
            if isinstance(action, SubTask):
                print(
                    info(
                        f"[SubTask] launching subagent "
                        f"(max {action.max_steps} steps): "
                        f"{action.prompt[:80]}..."
                    )
                )
                sub_agent = ReActAgent(self.llm_client)
                sub_result = sub_agent.run(
                    question=action.prompt,
                    max_steps=action.max_steps,
                    response_cls=SubResponse,
                    tool_classes=get_sub_tool_classes(),
                )
                print(info(f"[SubTask] result: {sub_result[:120]}..."))
                self.history.append(
                    f"SubTask ({action.prompt[:60]}...) -> {sub_result}"
                )
                continue

            # -- 5c. Finish --
            if isinstance(action, Finish):
                answer = action.answer
                print(f"{success('[Done]')} {answer}")
                # persist Q&A in history for multi-turn context inheritance
                self.history.append(f"Question: {question}")
                self.history.append(f"Answer: {answer}")
                return answer

            # -- 5d. regular tool --
            tool_name: str = getattr(action, "kind", "?")
            print(f"{tool('[Tool]')} {tool_name}")
            try:
                fn = getattr(action, "execute", None)
                if callable(fn):
                    result = fn()
                else:
                    result = f"Error: tool '{tool_name}' does not implement execute()"
            except Exception as exc:
                result = f"Error: {exc}"
            self.history.append(f"Action: {tool_name} -> {result}")

        return "Maximum steps reached; could not produce a final answer."


# ============================================================
# Demo
# ============================================================
if __name__ == "__main__":
    # Response with Finish
    r1 = Response(thought="Done.", action=Finish(answer="Hello, world!"))
    print("========== Response (Finish) ==========")
    print("model_dump_json:", r1.model_dump_json(indent=2))

    # Response with SubTask
    r2 = Response(
        thought="Too complex; delegate to subagent.",
        action=SubTask(prompt="Analyze the data", max_steps=3),
    )
    print("\n========== Response (SubTask) ==========")
    print("model_dump_json:", r2.model_dump_json(indent=2))

    # SubResponse rejects SubTask
    print("\n========== SubResponse rejects SubTask ==========")
    try:
        SubResponse.model_validate_json(
            '{"thought": "t", "action": {"kind": "SubTask", "prompt": "x"}}'
        )
        print("ERROR: should have rejected SubTask in SubResponse")
    except ValidationError:
        print("Correctly rejected: SubTask not in SubTool union")

    # SubResponse accepts Search
    sr = SubResponse.model_validate_json(
        '{"thought": "need info", "action": {"kind": "Search", "query": "weather"}}'
    )
    print(f"\nSubResponse accepted Search: {type(sr.action).__name__}")

    print("\nAll demo tests passed!")
