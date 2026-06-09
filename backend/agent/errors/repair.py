"""消息修复流水线。

提供：
- _find_unpaired_messages       底层查找未配对 tool_call
- repair_unpaired_tool_calls    修复未配对 tool_call 的流水线环节（纯函数）
- repair_messages               流水线编排器（纯函数，同步）
"""

from __future__ import annotations

import uuid as _uuid
from collections.abc import Callable

from shared.types import Message, MessageRole, ToolExecutionStatus

# ── 流水线阶段类型 ──────────────────────────────────────
# 每个阶段签名为: (list[Message]) -> list[Message]
_PipelineStage = Callable[[list[Message]], list[Message]]


# ============================================================
# Pipeline Stage: repair unpaired tool calls
# ============================================================


def _find_unpaired_messages(messages: list[Message]) -> list[Message]:
    """扫描消息列表，找出所有 assistant 消息中尚未配对
    tool_result 的 tool_call，为每一个生成一条 Error tool Message。

    纯函数，不依赖 Session。
    """
    if not messages:
        return []

    # 收集所有已被 tool_result 配对的 tool_call_id
    paired: set[str] = set()
    for m in messages:
        if m.role == MessageRole.TOOL and m.tool_call_id:
            paired.add(m.tool_call_id)

    # 从尾部向前找最近一条有 tool_calls 的 assistant
    repairs: list[Message] = []
    for m in reversed(messages):
        if m.role != MessageRole.ASSISTANT:
            continue
        if not m.tool_calls:
            continue
        for tc in m.tool_calls:
            if tc.id and tc.id not in paired:
                repairs.append(
                    Message.tool_message(
                        id=_uuid.uuid4().hex,
                        turn_id=m.turn_id,
                        tool_call_id=tc.id,
                        tool_name=tc.function.name,
                        result=("Error: The user interrupted before this tool could execute."),
                        tool_status=ToolExecutionStatus.INTERRUPTED.value,
                        tool_status_source="repair",
                        tool_status_reason="user_interrupted_before_execution",
                    )
                )
        # Note: intentionally no break — fix ALL unpaired tool_calls,
        # not just the last assistant. Earlier messages may also have
        # unpaired calls (e.g. after a subagent interrupt).
        # _build_llm_context's close_open_tool_calls is the in-memory
        # safety net when repair=False at runtime.

    return repairs


def repair_unpaired_tool_calls(
    messages: list[Message],
) -> list[Message]:
    """修复未配对 tool_call（纯函数，流水线环节）。

    返回拼接了修复 Message 的新列表。不修改原列表。
    """
    repairs = _find_unpaired_messages(messages)
    if not repairs:
        return list(messages)
    return messages + repairs


# ============================================================
# Pipeline Orchestrator
# ============================================================


def repair_messages(
    messages: list[Message],
    *stages: _PipelineStage,
) -> list[Message]:
    """消息修复流水线编排器（纯函数，同步）。

    依次运行传入的修复流水线环节；默认运行所有内置阶段：
      1. repair_unpaired_tool_calls  — 补全未配对的 tool_call

    调用方可传入自定义阶段列表，或使用默认管线：
      >>> repair_messages(messages)
      >>> repair_messages(messages, repair_unpaired_tool_calls)

    SSE 推送、Session 增量持久化等副作用由调用方处理。
    """
    if not stages:
        stages = (repair_unpaired_tool_calls,)

    result = list(messages)
    for stage in stages:
        result = stage(result)
    return result
