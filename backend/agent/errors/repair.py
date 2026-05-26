"""转录修复流水线。

提供：
- _find_unpaired_transcripts    底层查找未配对 tool_call
- repair_unpaired_tool_calls    修复未配对 tool_call 的流水线环节（纯函数）
- repair_transcripts            流水线编排器（纯函数，同步）
"""

from __future__ import annotations

import uuid as _uuid
from typing import Callable

from agent.transcript import Transcript

# ── 流水线阶段类型 ──────────────────────────────────────
# 每个阶段签名为: (list[Transcript]) -> list[Transcript]
_PipelineStage = Callable[[list[Transcript]], list[Transcript]]


# ============================================================
# Pipeline Stage: repair unpaired tool calls
# ============================================================


def _find_unpaired_transcripts(transcripts: list[Transcript]) -> list[Transcript]:
    """扫描 transcript 列表，找出最近一条 assistant 消息中尚未配对
    tool_result 的 tool_call，为每一个生成一条 Error tool_result Transcript。

    纯函数，不依赖 Session。
    """
    if not transcripts:
        return []

    # 收集所有已被 tool_result 配对的 tool_call_id
    paired: set[str] = set()
    for t in transcripts:
        if t.kind == "tool_result":
            tcid = t.message.get("tool_call_id", "")
            if tcid:
                paired.add(tcid)

    # 从尾部向前找最近一条有 tool_calls 的 assistant
    repairs: list[Transcript] = []
    for t in reversed(transcripts):
        if t.kind != "assistant":
            continue
        tool_calls = t.message.get("tool_calls", [])
        if not tool_calls:
            continue
        for tc in tool_calls:
            tcid = tc.get("id", "")
            if tcid and tcid not in paired:
                repairs.append(
                    Transcript(
                        id=_uuid.uuid4().hex,
                        kind="tool_result",
                        message={
                            "tool_call_id": tcid,
                            "tool_name": tc.get("function", {}).get("name", "unknown"),
                            "arguments": tc.get("function", {}).get("arguments", ""),
                            "result": (
                                "Error: The user interrupted before "
                                "this tool could execute."
                            ),
                        },
                    )
                )
        break  # 只处理最近一条 assistant 消息

    return repairs


def repair_unpaired_tool_calls(
    transcripts: list[Transcript],
) -> list[Transcript]:
    """修复未配对 tool_call（纯函数，流水线环节）。

    返回拼接了修复 Transcript 的新列表。不修改原列表。
    """
    repairs = _find_unpaired_transcripts(transcripts)
    if not repairs:
        return list(transcripts)
    return transcripts + repairs


# ============================================================
# Pipeline Orchestrator
# ============================================================


def repair_transcripts(
    transcripts: list[Transcript],
    *stages: _PipelineStage,
) -> list[Transcript]:
    """转录修复流水线编排器（纯函数，同步）。

    依次运行传入的修复流水线环节；默认运行所有内置阶段：
      1. repair_unpaired_tool_calls  — 补全未配对的 tool_call

    调用方可传入自定义阶段列表，或使用默认管线：
      >>> repair_transcripts(transcripts)
      >>> repair_transcripts(transcripts, repair_unpaired_tool_calls)

    SSE 推送、Session 增量持久化等副作用由调用方处理。
    """
    if not stages:
        stages = (repair_unpaired_tool_calls,)

    result = list(transcripts)
    for stage in stages:
        result = stage(result)
    return result
