"""Integration test: real LLM conversation verifies TranscriptStream
message building end-to-end.

Requires: .env with LLM_API_KEY (and optionally LLM_MODEL_ID / LLM_BASE_URL)
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from agent.llm import HelloAgentsLLM
from agent.scheduler import Scheduler
from agent.session import Session
from agent.tools.shell import Shell
from agent.tools.toolset import ToolSet
from agent.transcript import Transcript, TranscriptStream

# ── helpers ────────────────────────────────────────────


def _simple_mock_sandbox() -> MagicMock:
    """Minimal sandbox for Shell: stream_shell yields one chunk, exit 0."""
    sb = MagicMock()
    sb.workspace = "/tmp/test_stream"
    sb.session_id = "test-stream"

    async def _stream(cmd, timeout_ms, interrupt_event=None):
        yield f"mock output for: {cmd}"

    sb.stream_shell = _stream
    terminal_mock = MagicMock()
    terminal_mock._last_exit_code = 0
    sb.terminal = terminal_mock
    return sb


def _transcripts_by_kind(transcripts: list[Transcript], kind: str) -> list[Transcript]:
    return [t for t in transcripts if t.kind == kind]


# ── tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_real_llm_stream_builds_complete_message():
    """Ask the real LLM to call a Shell tool; verify TranscriptStream
    produces a complete, correctly structured assistant message."""

    llm = HelloAgentsLLM()
    sandbox = _simple_mock_sandbox()

    with patch("agent.session._save_transcript_sync", MagicMock()):
        with patch("agent.session._rewrite_messages_file", MagicMock()):
            session = Session(
                llm_client=llm,
                toolset=ToolSet([Shell]),
                sandbox=sandbox,
                session_id="test-stream",
            )

    channel = TranscriptStream()
    q = channel.subscribe()
    sse_events: list = []

    async def _drain():
        while True:
            ev = await q.get()
            if ev is None:
                return
            sse_events.append(ev)

    drainer = asyncio.create_task(_drain())

    # Prompt: explicitly name the tool and its arguments
    prompt = (
        "Call the Shell tool with exactly these arguments:\n"
        '  command: "echo hello"\n'
        "  timeout_ms: 5000\n"
        "Do not reply with any text. Only call this one tool."
    )

    scheduler = Scheduler()
    scheduler.start(session, prompt, channel=channel, max_steps=2)

    task = scheduler._loop_task
    assert task is not None
    try:
        await asyncio.wait_for(task, timeout=30.0)
    except asyncio.TimeoutError:
        pytest.fail("Scheduler timed out (LLM may be slow or unresponsive)")

    channel.close()
    await drainer

    # ── Verifications ──────────────────────────────────

    transcripts: list[Transcript] = session._transcripts
    assistants = _transcripts_by_kind(transcripts, "assistant")
    tool_results = _transcripts_by_kind(transcripts, "tool_result")

    # 1. Got at least one assistant with tool_calls
    assert len(assistants) >= 1, (
        f"No assistant transcript found.\n"
        f"Transcript kinds: {[t.kind for t in transcripts]}"
    )

    assistant = assistants[0]
    msg = assistant.message

    tool_calls = msg.get("tool_calls", [])
    assert isinstance(tool_calls, list) and len(tool_calls) >= 1, (
        f"Expected tool_calls in assistant message, got: {json.dumps(msg, indent=2)}"
    )

    # 2. Each tool_call has required fields
    for i, tc in enumerate(tool_calls):
        assert tc.get("id"), f"tool_call[{i}] missing id"
        assert tc.get("type") == "function", f"tool_call[{i}] type != function"
        fn = tc.get("function", {})
        assert fn.get("name"), f"tool_call[{i}] missing function.name"
        # arguments should be valid JSON
        args_str = fn.get("arguments", "")
        assert args_str, f"tool_call[{i}] missing function.arguments"
        try:
            json.loads(args_str)
        except json.JSONDecodeError:
            pytest.fail(f"tool_call[{i}] arguments not valid JSON: {args_str!r}")

    # 3. Every tool_call has a corresponding tool_result
    tool_call_ids = {tc["id"] for tc in tool_calls}
    tool_result_ids = {tr.message.get("tool_call_id", "") for tr in tool_results}
    unpaired = tool_call_ids - tool_result_ids
    assert not unpaired, (
        f"Unpaired tool_calls: {unpaired}\n"
        f"tool_call_ids: {tool_call_ids}\n"
        f"tool_result_ids: {tool_result_ids}"
    )

    # 4. tool_result messages have proper structure
    for tr in tool_results:
        tr_msg = tr.message
        assert tr_msg.get("tool_call_id"), "tool_result missing tool_call_id"
        assert tr_msg.get("tool_name"), "tool_result missing tool_name"
        assert "result" in tr_msg, "tool_result missing result"

    # 5. SSE flush events match transcripts (same count, same ids)
    flush_ids = {
        e.payload["transcript_id"]
        for e in sse_events
        if getattr(e, "name", None) == "flush"
    }
    transcript_ids = {t.id for t in transcripts}
    missing_from_sse = transcript_ids - flush_ids
    assert not missing_from_sse, (
        f"Transcripts missing from SSE flush events: {missing_from_sse}"
    )

    extra_in_sse = flush_ids - transcript_ids
    assert not extra_in_sse, (
        f"SSE flush events without matching transcript: {extra_in_sse}"
    )

    # 6. Flush event payload message matches transcript message
    for t in transcripts:
        matching = [
            e
            for e in sse_events
            if getattr(e, "name", None) == "flush"
            and e.payload["transcript_id"] == t.id
        ]
        assert len(matching) == 1, (
            f"Expected exactly 1 flush event for {t.id}, got {len(matching)}"
        )
        sse_msg = matching[0].payload["message"]
        assert sse_msg == t.message, (
            f"SSE flush message != transcript message for {t.id}:\n"
            f"  SSE: {json.dumps(sse_msg)}\n"
            f"  T:   {json.dumps(t.message)}"
        )
