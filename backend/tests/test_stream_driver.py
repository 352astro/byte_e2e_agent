"""Tests for StreamDriverHook with the new Message-based StreamEvent API."""

from __future__ import annotations

import asyncio

import pytest

from agent.hook.stream_driver import StreamDriverHook
from shared.types import Message, StreamEvent, StreamEventKind

# ═══════════════════════════════════════════════════════════
# Subscribe / Unsubscribe
# ═══════════════════════════════════════════════════════════


class TestSubscribeUnsubscribe:
    def test_subscribe_returns_asyncio_queue(self):
        """driver.subscribe() returns an asyncio.Queue."""
        driver = StreamDriverHook()
        q = driver.subscribe()
        assert isinstance(q, asyncio.Queue)

    def test_unsubscribe_removes_queue(self):
        """driver.unsubscribe(q) removes the queue from subscribers."""
        driver = StreamDriverHook()
        q = driver.subscribe()
        assert q in driver._subscribers

        driver.unsubscribe(q)
        assert q not in driver._subscribers

    def test_unsubscribe_twice_does_not_raise(self):
        """Unsubscribing the same queue twice is safe."""
        driver = StreamDriverHook()
        q = driver.subscribe()
        driver.unsubscribe(q)
        driver.unsubscribe(q)  # no-op, should not raise

    @pytest.mark.asyncio
    async def test_close_sends_none_to_all_subscribers(self):
        """driver.close() sends None to all subscribers."""
        driver = StreamDriverHook()
        q1 = driver.subscribe()
        q2 = driver.subscribe()

        driver.close()

        assert q1.get_nowait() is None
        assert q2.get_nowait() is None
        assert driver._subscribers == []

    @pytest.mark.asyncio
    async def test_subscribe_after_close_gets_none_immediately(self):
        """Subscribe after close gets None immediately."""
        driver = StreamDriverHook()
        driver.close()

        q = driver.subscribe()
        ev = q.get_nowait()
        assert ev is None


# ═══════════════════════════════════════════════════════════
# Event Broadcasting — message_start
# ═══════════════════════════════════════════════════════════


class TestMessageStart:
    @pytest.mark.asyncio
    async def test_on_message_start_broadcasts_message_start_event(self):
        """on_message_start → StreamEvent with kind=message_start, message_id, turn_id."""
        driver = StreamDriverHook()
        q = driver.subscribe()

        msg = Message.assistant_message("m1", "t1")
        await driver.on_message_start(msg=msg)

        ev = q.get_nowait()
        assert ev is not None
        assert ev.kind == StreamEventKind.MESSAGE_START
        assert ev.message_id == "m1"
        assert ev.turn_id == "t1"


# ═══════════════════════════════════════════════════════════
# Event Broadcasting — chunk_delta
# ═══════════════════════════════════════════════════════════


class TestChunkDelta:
    @pytest.mark.asyncio
    async def test_content_field_broadcasts_chunk_delta(self):
        """on_chunk_delta with field='content' → chunk_delta with field='content'."""
        driver = StreamDriverHook()
        q = driver.subscribe()

        msg = Message.assistant_message("m1", "t1")
        await driver.on_chunk_delta(msg=msg, field="content", delta="hello")

        ev = q.get_nowait()
        assert ev is not None
        assert ev.kind == StreamEventKind.CHUNK_DELTA
        assert ev.field == "content"
        assert ev.delta == "hello"
        assert ev.message_id == "m1"

    @pytest.mark.asyncio
    async def test_reasoning_field_broadcasts_chunk_delta(self):
        """on_chunk_delta with field='reasoning' → chunk_delta with field='reasoning'."""
        driver = StreamDriverHook()
        q = driver.subscribe()

        msg = Message.assistant_message("m1", "t1")
        await driver.on_chunk_delta(msg=msg, field="reasoning", delta="think")

        ev = q.get_nowait()
        assert ev is not None
        assert ev.kind == StreamEventKind.CHUNK_DELTA
        assert ev.field == "reasoning"
        assert ev.delta == "think"

    @pytest.mark.asyncio
    async def test_empty_delta_skipped(self):
        """Empty delta → no event queued."""
        driver = StreamDriverHook()
        q = driver.subscribe()

        msg = Message.assistant_message("m1", "t1")
        await driver.on_chunk_delta(msg=msg, field="content", delta="")

        assert q.empty()

    @pytest.mark.asyncio
    async def test_empty_message_id_skipped(self):
        """Empty msg.id → no event queued."""
        driver = StreamDriverHook()
        q = driver.subscribe()

        msg = Message.assistant_message("", "t1")  # empty id
        await driver.on_chunk_delta(msg=msg, field="content", delta="hello")

        assert q.empty()

    @pytest.mark.asyncio
    async def test_with_tool_name_in_metadata(self):
        """tool_name is propagated in the StreamEvent."""
        driver = StreamDriverHook()
        q = driver.subscribe()

        msg = Message.assistant_message("m1", "t1")
        await driver.on_chunk_delta(
            msg=msg, field="content", delta="call", tool_name="Shell"
        )

        ev = q.get_nowait()
        assert ev is not None
        assert ev.tool_name == "Shell"


# ═══════════════════════════════════════════════════════════
# Event Broadcasting — chunk_complete
# ═══════════════════════════════════════════════════════════


class TestChunkComplete:
    @pytest.mark.asyncio
    async def test_on_chunk_complete_broadcasts_chunk_complete_event(self):
        """on_chunk_complete → chunk_complete with full_content, tool_name, tool_args."""
        driver = StreamDriverHook()
        q = driver.subscribe()

        msg = Message.assistant_message("m1", "t1")
        await driver.on_chunk_complete(
            msg=msg,
            field="tool_calls",
            full_content='{"cmd":"ls"}',
            tool_name="Shell",
            tool_args='{"cmd":"ls"}',
        )

        ev = q.get_nowait()
        assert ev is not None
        assert ev.kind == StreamEventKind.CHUNK_COMPLETE
        assert ev.field == "tool_calls"
        assert ev.full_content == '{"cmd":"ls"}'
        assert ev.tool_name == "Shell"
        assert ev.tool_args == '{"cmd":"ls"}'

    @pytest.mark.asyncio
    async def test_on_chunk_complete_skips_empty_message_id(self):
        """on_chunk_complete skips when msg.id is empty."""
        driver = StreamDriverHook()
        q = driver.subscribe()

        msg = Message.assistant_message("", "t1")  # empty id
        await driver.on_chunk_complete(
            msg=msg,
            field="tool_calls",
            full_content="{}",
        )

        assert q.empty()

    @pytest.mark.asyncio
    async def test_on_chunk_complete_with_is_error(self):
        """on_chunk_complete with is_error=True propagates the flag."""
        driver = StreamDriverHook()
        q = driver.subscribe()

        msg = Message.assistant_message("m1", "t1")
        await driver.on_chunk_complete(
            msg=msg,
            field="tool_result",
            full_content="error output",
            is_error=True,
        )

        ev = q.get_nowait()
        assert ev is not None
        assert ev.kind == StreamEventKind.CHUNK_COMPLETE
        assert ev.is_error is True


# ═══════════════════════════════════════════════════════════
# Event Broadcasting — message_finish
# ═══════════════════════════════════════════════════════════


class TestMessageFinish:
    @pytest.mark.asyncio
    async def test_on_message_finish_broadcasts_message_finish_event(self):
        """on_message_finish → message_finish event."""
        driver = StreamDriverHook()
        q = driver.subscribe()

        msg = Message.assistant_message("m1", "t1")
        await driver.on_message_finish(msg=msg)

        ev = q.get_nowait()
        assert ev is not None
        assert ev.kind == StreamEventKind.MESSAGE_FINISH
        assert ev.message_id == "m1"


# ═══════════════════════════════════════════════════════════
# Event Broadcasting — turn_complete
# ═══════════════════════════════════════════════════════════


class TestTurnComplete:
    @pytest.mark.asyncio
    async def test_on_turn_end_broadcasts_turn_complete_event(self):
        """on_turn_end → turn_complete with input_tokens, output_tokens."""
        driver = StreamDriverHook()
        q = driver.subscribe()

        await driver.on_turn_end(turn_id="t1", input_tokens=100, output_tokens=50)

        ev = q.get_nowait()
        assert ev is not None
        assert ev.kind == StreamEventKind.TURN_COMPLETE
        assert ev.turn_id == "t1"
        assert ev.input_tokens == 100
        assert ev.output_tokens == 50

    @pytest.mark.asyncio
    async def test_on_turn_end_empty_turn_id_skipped(self):
        """on_turn_end with empty turn_id is skipped."""
        driver = StreamDriverHook()
        q = driver.subscribe()

        await driver.on_turn_end(turn_id="", input_tokens=0, output_tokens=0)

        assert q.empty()


# ═══════════════════════════════════════════════════════════
# Event Broadcasting — interrupted
# ═══════════════════════════════════════════════════════════


class TestInterrupted:
    @pytest.mark.asyncio
    async def test_on_message_error_broadcasts_interrupted_event(self):
        """on_message_error → interrupted with reason set from the exception."""
        driver = StreamDriverHook()
        q = driver.subscribe()

        msg = Message.assistant_message("m1", "t1")
        await driver.on_message_error(msg=msg, error=RuntimeError("boom"))

        ev = q.get_nowait()
        assert ev is not None
        assert ev.kind == StreamEventKind.INTERRUPTED
        assert ev.reason == "boom"


# ═══════════════════════════════════════════════════════════
# Multiple Subscribers
# ═══════════════════════════════════════════════════════════


class TestMultipleSubscribers:
    @pytest.mark.asyncio
    async def test_two_subscribers_both_receive_same_events(self):
        """Two subscribers both receive the same events."""
        driver = StreamDriverHook()
        q1 = driver.subscribe()
        q2 = driver.subscribe()

        msg = Message.assistant_message("m1", "t1")
        await driver.on_message_start(msg=msg)
        await driver.on_chunk_delta(msg=msg, field="content", delta="hello")
        await driver.on_message_finish(msg=msg)

        for q in [q1, q2]:
            ev1 = q.get_nowait()
            assert ev1 is not None
            assert ev1.kind == StreamEventKind.MESSAGE_START
            ev2 = q.get_nowait()
            assert ev2 is not None
            assert ev2.kind == StreamEventKind.CHUNK_DELTA
            ev3 = q.get_nowait()
            assert ev3 is not None
            assert ev3.kind == StreamEventKind.MESSAGE_FINISH
            assert q.empty()


# ═══════════════════════════════════════════════════════════
# Dead Subscriber Cleanup
# ═══════════════════════════════════════════════════════════


class TestDeadSubscriberCleanup:
    @pytest.mark.asyncio
    async def test_queue_full_subscriber_removed(self):
        """When a subscriber's queue is full, it gets removed from subscribers."""
        driver = StreamDriverHook()

        # Create a queue with maxsize=1, fill it first
        q = asyncio.Queue(maxsize=1)
        driver._subscribers.append(q)
        q.put_nowait(StreamEvent.message_start("t", "m"))  # queue is now full

        # Broadcast an event — this should trigger dead subscriber cleanup
        msg = Message.assistant_message("m1", "t1")
        await driver.on_message_finish(msg=msg)

        # The full queue should have been removed
        assert q not in driver._subscribers
