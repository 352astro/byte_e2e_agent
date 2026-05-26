"""Test runtime repair: interrupt during multi-tool execution
should produce correctly paired transcripts and SSE repair events.

Requires: pytest, pytest-asyncio
  pip install pytest pytest-asyncio
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from agent.errors import repair_transcripts
from agent.scheduler import Scheduler
from agent.session import Session
from agent.tools.shell import Shell
from agent.tools.toolset import ToolSet
from agent.transcript import StreamTranscriptCompletion, Transcript

# ── Number of tool_calls the mock LLM will return ──────
NUM_TOOL_CALLS = 10


# ── helpers ────────────────────────────────────────────


def _make_tool_call(idx: int) -> dict:
    return {
        "id": f"call_{idx}",
        "type": "function",
        "function": {
            "name": "Shell",
            "arguments": '{"command": "sleep 100", "timeout_ms": 120000}',
        },
    }


def _mock_think_stream(num_calls: int = NUM_TOOL_CALLS):
    """Return an async generator that simulates an LLM streaming tool_calls.
    Only emits tool_calls on the first invocation; returns stop thereafter
    to prevent infinite looping.
    """
    called = 0

    async def _stream(messages, tools, metrics_context=None):
        nonlocal called
        called += 1
        if called == 1:
            for i in range(num_calls):
                tc = _make_tool_call(i)
                yield {
                    "kind": "tool_call_chunk",
                    "tool_call": {
                        "index": i,
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    },
                }
            yield {"kind": "finish_reason", "finish_reason": "tool_calls"}
        else:
            yield {
                "kind": "content",
                "token": "All done.",
            }
            yield {"kind": "finish_reason", "finish_reason": "stop"}

    return _stream


def _build_mock_sandbox(
    signal_test: asyncio.Event,
    signal_continue: asyncio.Event,
    tool_count: list[int],  # mutable counter
    release_after: int,
) -> MagicMock:
    """Build a MagicMock sandbox whose stream_shell blocks on
    *signal_continue* after *release_after* invocations.

    *signal_test* is set when the N-th tool completes, so the test
    knows it can now set the interrupt flag and then release the
    blocked tools via *signal_continue*.
    """
    sb = MagicMock()
    sb.workspace = "/tmp/test_repair"
    sb.session_id = "test-session"

    async def _stream(cmd, timeout_ms, interrupt_event=None):
        tool_count[0] += 1
        if tool_count[0] == release_after:
            # Tell test: requested number of tools have completed
            signal_test.set()
        if tool_count[0] > release_after:
            # Block until test releases us (after setting interrupt)
            await signal_continue.wait()
        yield "shell ok"

    sb.stream_shell = _stream

    terminal_mock = MagicMock()
    terminal_mock._last_exit_code = 0
    sb.terminal = terminal_mock

    return sb


# ── tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_interrupt_repairs_unpaired_tool_calls():
    """Full pipeline: LLM returns N tool_calls → interrupt mid-way →
    repair via _apply_repairs → verify SSE + transcript pairing.
    """
    RELEASE_AFTER = 3  # let 3 tools execute, block the rest

    signal_test = asyncio.Event()
    signal_continue = asyncio.Event()
    tool_count = [0]  # list for mutable closure

    mock_llm = MagicMock()
    mock_llm.think_stream = _mock_think_stream(NUM_TOOL_CALLS)
    mock_sandbox = _build_mock_sandbox(
        signal_test, signal_continue, tool_count, RELEASE_AFTER
    )

    with patch("agent.session._save_transcript_sync", MagicMock()):
        with patch("agent.session._rewrite_messages_file", MagicMock()):
            session = Session(
                llm_client=mock_llm,
                toolset=ToolSet([Shell]),
                sandbox=mock_sandbox,
                session_id="test-session",
            )

    # ── SSE subscriber ──────────────────────────────────
    channel = StreamTranscriptCompletion()
    q = channel.subscribe()
    sse_events: list = []

    async def _drain():
        while True:
            ev = await q.get()
            if ev is None:
                return
            sse_events.append(ev)

    drainer = asyncio.create_task(_drain())

    # ── Start scheduler ─────────────────────────────────
    scheduler = Scheduler()
    scheduler.start(session, "run 10 sleeps", channel=channel, max_steps=2)

    # ── Wait for signal: N tools have completed ─────────
    try:
        await asyncio.wait_for(signal_test.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail(
            f"Timed out waiting for {RELEASE_AFTER} tools to execute "
            f"(only {tool_count[0]} ran)"
        )

    # ── Now interrupt ───────────────────────────────────
    # Tools N+1..10 are blocked on signal_continue.
    # Set interrupt first, then release them.
    scheduler._interrupt_event.set()
    signal_continue.set()

    # Wait for full shutdown
    task = scheduler._loop_task
    if task is not None:
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail("Scheduler did not shut down within timeout")
        except Exception:
            pass  # expected: InterruptedError was raised and handled

    # Drain remaining SSE events
    channel.close()
    await drainer

    # ── Assertions ──────────────────────────────────────

    transcripts: list[Transcript] = session._transcripts
    tool_call_ids: set[str] = set()
    tool_result_ids: set[str] = set()
    repair_count = 0

    for t in transcripts:
        if t.kind == "assistant":
            for tc in t.message.get("tool_calls", []):
                tool_call_ids.add(tc["id"])
        elif t.kind == "tool_result":
            tcid = t.message.get("tool_call_id", "")
            if tcid:
                tool_result_ids.add(tcid)
            if "interrupted before" in str(t.message.get("result", "")):
                repair_count += 1

    # 5a. Every tool_call has a corresponding tool_result
    unpaired = tool_call_ids - tool_result_ids
    assert not unpaired, (
        f"Unpaired tool_calls remain: {unpaired}\n"
        f"tool_call_ids ({len(tool_call_ids)}): {sorted(tool_call_ids)}\n"
        f"tool_result_ids ({len(tool_result_ids)}): {sorted(tool_result_ids)}"
    )

    # 5b. Repair tool_results were sent via SSE
    flush_events = [e for e in sse_events if getattr(e, "name", None) == "flush"]
    sse_repair_results = [
        e
        for e in flush_events
        if e.payload.get("kind") == "tool_result"
        and "interrupted before" in str(e.payload.get("message", {}).get("result", ""))
    ]
    assert len(sse_repair_results) > 0, (
        "No repair tool_result events in SSE stream.\n"
        f"Total flush events: {len(flush_events)}\n"
        f"Kinds: {[e.payload.get('kind') for e in flush_events]}"
    )

    # 5c. repair count in transcripts == repair count in SSE
    assert repair_count == len(sse_repair_results), (
        f"Mismatch: {repair_count} repair transcripts vs "
        f"{len(sse_repair_results)} repair SSE events"
    )

    # 5d. Total tool_results = total tool_calls
    assert len(tool_result_ids) == NUM_TOOL_CALLS, (
        f"Expected {NUM_TOOL_CALLS} tool_results, got {len(tool_result_ids)}"
    )

    # 5e. Some tools executed, some repaired
    executed = len(tool_result_ids) - repair_count
    assert executed >= 1, "Expected at least 1 tool to execute before interrupt"
    assert repair_count >= 1, "Expected at least 1 repair due to interrupt"

    # 5f. repair_transcripts is idempotent
    before = len(session._transcripts)
    _ = repair_transcripts(session._transcripts)
    assert len(session._transcripts) == before, (
        "repair_transcripts should be idempotent on already-repaired transcripts"
    )


@pytest.mark.asyncio
async def test_repair_transcripts_idempotent():
    """Calling repair_transcripts on already-paired transcripts adds nothing."""
    transcripts = [
        Transcript(
            id="a1",
            kind="assistant",
            message={
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tc_1",
                        "type": "function",
                        "function": {
                            "name": "Shell",
                            "arguments": '{"command": "ls"}',
                        },
                    },
                    {
                        "id": "tc_2",
                        "type": "function",
                        "function": {
                            "name": "Shell",
                            "arguments": '{"command": "pwd"}',
                        },
                    },
                ],
            },
        ),
        Transcript(
            id="r1",
            kind="tool_result",
            message={
                "tool_call_id": "tc_1",
                "tool_name": "Shell",
                "arguments": '{"command": "ls"}',
                "result": "file1.txt",
            },
        ),
        Transcript(
            id="r2",
            kind="tool_result",
            message={
                "tool_call_id": "tc_2",
                "tool_name": "Shell",
                "arguments": '{"command": "pwd"}',
                "result": "/home",
            },
        ),
    ]

    repaired = repair_transcripts(transcripts)
    assert len(repaired) == len(transcripts), (
        f"Expected no new transcripts, got {len(repaired) - len(transcripts)} extra"
    )


@pytest.mark.asyncio
async def test_repair_transcripts_fills_unpaired():
    """repair_transcripts adds error tool_results for unpaired tool_calls."""
    transcripts = [
        Transcript(
            id="a1",
            kind="assistant",
            message={
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tc_1",
                        "type": "function",
                        "function": {
                            "name": "Shell",
                            "arguments": '{"command": "ls"}',
                        },
                    },
                    {
                        "id": "tc_2",
                        "type": "function",
                        "function": {
                            "name": "Shell",
                            "arguments": '{"command": "pwd"}',
                        },
                    },
                ],
            },
        ),
        # Only tc_1 has a result; tc_2 is unpaired
        Transcript(
            id="r1",
            kind="tool_result",
            message={
                "tool_call_id": "tc_1",
                "tool_name": "Shell",
                "arguments": '{"command": "ls"}',
                "result": "file1.txt",
            },
        ),
    ]

    repaired = repair_transcripts(transcripts)
    assert len(repaired) == len(transcripts) + 1, (
        f"Expected 1 repair transcript, got {len(repaired) - len(transcripts)}"
    )

    new = repaired[-1]
    assert new.kind == "tool_result"
    assert new.message["tool_call_id"] == "tc_2"
    assert "interrupted before" in new.message["result"]
