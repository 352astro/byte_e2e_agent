"""
Plan 系列工具：PlanItem / PlanRewrite / PlanAdvance。

PlanRewrite 和 PlanAdvance 不走 execute()——它们由 ReActAgent 循环中的
PlanManager 拦截处理。这里仅定义其 Pydantic 模型以纳入 Tool 鉴别联合。
"""

from typing import Literal

from pydantic import BaseModel, Field

from agent.tools.base import BaseTool

# ============================================================
# PlanItem
# ============================================================

State = Literal["todo", "in_progress", "done", "failed"]

_STATE_DESCRIPTIONS: dict[str, str] = {
    "todo": "not yet started",
    "in_progress": "currently executing (only one at a time)",
    "done": "completed successfully",
    "failed": "execution failed",
}


class PlanItem(BaseModel):
    """A single task in the plan."""

    description: str = Field(
        ...,
        description="Task description in one sentence",
    )
    state: State = Field(
        default="todo",
        description="Current state: "
        + " | ".join(f"{k}={v}" for k, v in _STATE_DESCRIPTIONS.items()),
    )


# ============================================================
# PlanRewrite
# ============================================================


class PlanRewrite(BaseTool):
    """
    Replace the ENTIRE plan with a new list of items.

    WARNING: this unconditionally discards the current plan,
    including any in_progress or todo items. All progress is lost.
    Only use this when the current plan is fundamentally wrong
    or has been completed/failed. Prefer PlanAdvance for normal
    step-by-step progress.
    """

    items: list[PlanItem] = Field(
        ...,
        description=(
            "Complete new plan as a list of tasks. "
            "CAUTION: this replaces ALL existing items - "
            "any in_progress work will be abandoned."
        ),
    )


# ============================================================
# PlanAdvance
# ============================================================


class PlanAdvance(BaseTool):
    """
    Advance the first non-done plan item to a target state.

    Auto-locate: scans the list and picks the first item whose
    state is in_progress / failed / todo.

    Allowed forward transitions (skip allowed):
      todo / failed  ->  in_progress / done / failed
      in_progress     ->  done / failed
    """

    state: State = Field(
        ...,
        description="Target state for the current active item",
    )
