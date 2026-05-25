"""
Interrupt — 中断信号、tool_call 修复。

提供：
- InterruptedError  中断异常
- repair_unpaired_tools  补齐未执行的 tool_call 为 Error tool_result
"""

from __future__ import annotations

import uuid as _uuid

from agent.session import Session
from agent.transcript import StreamTranscriptCompletion


class InterruptedError(Exception):
    """Raised when the user interrupts the agent loop."""

    pass

def _find_unpaired(session: "Session") -> list[tuple[str, dict]]:
    """Return list of (result_id, result_msg) for unpaired tool_calls."""
    transcripts = session._transcripts
    if not transcripts:
        return []

    paired: set[str] = set()
    for t in transcripts:
        if t.kind == "tool_result":
            tcid = t.message.get("tool_call_id", "")
            if tcid:
                paired.add(tcid)

    repairs: list[tuple[str, dict]] = []
    for t in reversed(transcripts):
        if t.kind != "assistant":
            continue
        tool_calls = t.message.get("tool_calls", [])
        if not tool_calls:
            continue
        for tc in tool_calls:
            tcid = tc.get("id", "")
            if tcid and tcid not in paired:
                result_id = _uuid.uuid4().hex
                result_msg = {
                    "tool_call_id": tcid,
                    "tool_name": tc.get("function", {}).get("name", "unknown"),
                    "arguments": tc.get("function", {}).get("arguments", ""),
                    "result": "Error: The user interrupted before this tool could execute.",
                }
                repairs.append((result_id, result_msg))
        break
    return repairs


def repair_unpaired_tools(session: "Session") -> None:
    """Fill unpaired tool_calls with Error tool_results (sync, no SSE)."""
    for result_id, result_msg in _find_unpaired(session):
        session.add_transcript("tool_result", result_msg, result_id)


async def repair_unpaired_tools_async(
    session: "Session",
    channel: "StreamTranscriptCompletion",
) -> None:
    """Fill unpaired tool_calls and flush each via SSE."""
    for result_id, result_msg in _find_unpaired(session):
        try:
            t = await channel.flush(result_id, "tool_result", result_msg)
            session.add_transcript(t.kind, t.message, t.id)
        except Exception:
            pass
