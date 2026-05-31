"""Comprehensive tests for the Pydantic types defined in shared/types.py.

Covers: Message, ToolCall, ToolCallFunction, StreamEvent, Turn
"""

from __future__ import annotations

import pytest

from shared.types import (
    Message,
    MessageRole,
    MessageStatus,
    StreamEvent,
    StreamEventKind,
    ToolCall,
    ToolCallFunction,
    Turn,
)

# ═══════════════════════════════════════════════════════════════════════
# ToolCallFunction
# ═══════════════════════════════════════════════════════════════════════


class TestToolCallFunction:
    """Tests for ToolCallFunction — the OpenAI-format function field."""

    def test_default_construction(self) -> None:
        """Default ToolCallFunction has empty name and arguments (not None)."""
        tcf = ToolCallFunction()
        assert tcf.name == ""
        assert tcf.arguments == ""

    def test_full_construction(self) -> None:
        """ToolCallFunction with explicit values."""
        tcf = ToolCallFunction(name="Shell", arguments='{"cmd":"ls"}')
        assert tcf.name == "Shell"
        assert tcf.arguments == '{"cmd":"ls"}'

    def test_model_dump(self) -> None:
        """model_dump() returns a plain dict."""
        tcf = ToolCallFunction(name="Shell", arguments='{"cmd":"ls"}')
        d = tcf.model_dump()
        assert d == {"name": "Shell", "arguments": '{"cmd":"ls"}'}

    def test_model_validate(self) -> None:
        """model_validate reconstructs from dict."""
        tcf = ToolCallFunction.model_validate(
            {"name": "Shell", "arguments": '{"cmd":"ls"}'}
        )
        assert tcf.name == "Shell"
        assert tcf.arguments == '{"cmd":"ls"}'

    def test_round_trip(self) -> None:
        """model_dump → model_validate produces an equivalent instance."""
        original = ToolCallFunction(name="Shell", arguments='{"cmd":"ls"}')
        restored = ToolCallFunction.model_validate(original.model_dump())
        assert restored == original


# ═══════════════════════════════════════════════════════════════════════
# ToolCall
# ═══════════════════════════════════════════════════════════════════════


class TestToolCall:
    """Tests for ToolCall — OpenAI-format tool call."""

    def test_default_construction(self) -> None:
        """Default ToolCall: empty id, type="function", empty ToolCallFunction."""
        tc = ToolCall()
        assert tc.id == ""
        assert tc.type == "function"
        assert isinstance(tc.function, ToolCallFunction)
        assert tc.function.name == ""
        assert tc.function.arguments == ""

    def test_full_construction_with_dict_function(self) -> None:
        """ToolCall with id and function passed as a dict (Pydantic coerces)."""
        tc = ToolCall(
            id="tc1",
            function={"name": "Shell", "arguments": '{"cmd":"ls"}'},
        )
        assert tc.id == "tc1"
        assert tc.type == "function"
        assert isinstance(tc.function, ToolCallFunction)
        assert tc.function.name == "Shell"
        assert tc.function.arguments == '{"cmd":"ls"}'

    def test_full_construction_with_toolcallfunction(self) -> None:
        """ToolCall with id and function passed as ToolCallFunction instance."""
        tcf = ToolCallFunction(name="Shell", arguments='{"cmd":"ls"}')
        tc = ToolCall(id="tc1", function=tcf)
        assert tc.id == "tc1"
        assert tc.function is tcf  # same object, no copy
        assert tc.function.name == "Shell"

    def test_model_dump(self) -> None:
        """model_dump() serializes nested ToolCallFunction."""
        tc = ToolCall(
            id="tc1",
            function={"name": "Shell", "arguments": '{"cmd":"ls"}'},
        )
        d = tc.model_dump()
        assert d["id"] == "tc1"
        assert d["type"] == "function"
        assert d["function"]["name"] == "Shell"
        assert d["function"]["arguments"] == '{"cmd":"ls"}'

    def test_model_dump_json_mode(self) -> None:
        """model_dump(mode='json') returns JSON-safe representation."""
        tc = ToolCall(
            id="tc1",
            function={"name": "Shell", "arguments": '{"cmd":"ls"}'},
        )
        d = tc.model_dump(mode="json")
        assert isinstance(d["id"], str)
        assert d["id"] == "tc1"
        assert d["function"]["name"] == "Shell"

    def test_model_validate(self) -> None:
        """model_validate reconstructs ToolCall from dict."""
        tc = ToolCall.model_validate(
            {
                "id": "tc1",
                "type": "function",
                "function": {"name": "Shell", "arguments": '{"cmd":"ls"}'},
            }
        )
        assert tc.id == "tc1"
        assert tc.function.name == "Shell"

    def test_round_trip(self) -> None:
        """model_dump → model_validate produces equivalent ToolCall."""
        original = ToolCall(
            id="tc1",
            function={"name": "Shell", "arguments": '{"cmd":"ls"}'},
        )
        restored = ToolCall.model_validate(original.model_dump())
        assert restored.id == original.id
        assert restored.function == original.function

    def test_default_values_not_none(self) -> None:
        """All default values are empty strings / lists, never None."""
        tc = ToolCall()
        assert tc.id is not None
        assert tc.type is not None
        assert tc.function is not None
        assert tc.function.name is not None
        assert tc.function.arguments is not None


# ═══════════════════════════════════════════════════════════════════════
# Message
# ═══════════════════════════════════════════════════════════════════════


class TestMessageFactories:
    """Tests for Message factory methods."""

    def test_assistant_message(self) -> None:
        """assistant_message() creates with STREAMING, ASSISTANT role, empty fields."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        assert msg.id == "msg1"
        assert msg.turn_id == "t1"
        assert msg.role == MessageRole.ASSISTANT
        assert msg.status == MessageStatus.STREAMING
        # All content fields should be empty by default
        assert msg.content == ""
        assert msg.reasoning == ""
        assert msg.tool_calls == []
        assert msg.tool_result == ""
        assert msg.tool_call_id == ""
        assert msg.tool_name == ""
        assert msg.error == ""

    def test_user_message(self) -> None:
        """user_message() creates with COMPLETE, USER role, content filled."""
        msg = Message.user_message(id="msg2", turn_id="t1", content="Hello, world!")
        assert msg.id == "msg2"
        assert msg.turn_id == "t1"
        assert msg.role == MessageRole.USER
        assert msg.status == MessageStatus.COMPLETE
        assert msg.content == "Hello, world!"
        assert msg.reasoning == ""
        assert msg.tool_calls == []

    def test_tool_message(self) -> None:
        """tool_message() creates with TOOL role, all tool fields filled."""
        msg = Message.tool_message(
            id="msg3",
            turn_id="t1",
            tool_call_id="tc_abc",
            tool_name="Shell",
            result="$ ls\nfile.txt",
        )
        assert msg.id == "msg3"
        assert msg.turn_id == "t1"
        assert msg.role == MessageRole.TOOL
        assert msg.status == MessageStatus.COMPLETE
        assert msg.tool_call_id == "tc_abc"
        assert msg.tool_name == "Shell"
        assert msg.tool_result == "$ ls\nfile.txt"
        # Content/reasoning should be empty for tool messages
        assert msg.content == ""
        assert msg.reasoning == ""

    def test_error_message(self) -> None:
        """error_message() creates with ASSISTANT role, error filled, COMPLETE."""
        msg = Message.error_message(
            id="msg4",
            turn_id="t1",
            error="Something went wrong",
        )
        assert msg.id == "msg4"
        assert msg.turn_id == "t1"
        assert msg.role == MessageRole.ASSISTANT
        assert msg.status == MessageStatus.COMPLETE
        assert msg.error == "Something went wrong"
        assert msg.content == ""
        assert msg.reasoning == ""


class TestMessageContentAccumulation:
    """Tests for streaming content accumulation on Message."""

    def test_content_accumulation(self) -> None:
        """content can be accumulated with += operator."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        msg.content += "hello"
        assert msg.content == "hello"
        msg.content += " world"
        assert msg.content == "hello world"

    def test_reasoning_accumulation(self) -> None:
        """reasoning can be accumulated with += operator."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        msg.reasoning += "I need to think"
        assert msg.reasoning == "I need to think"
        msg.reasoning += " more deeply"
        assert msg.reasoning == "I need to think more deeply"

    def test_both_fields_accumulate_independently(self) -> None:
        """content and reasoning accumulate independently."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        msg.content += "visible"
        msg.reasoning += "hidden"
        assert msg.content == "visible"
        assert msg.reasoning == "hidden"


class TestMessageToolCalls:
    """Tests for tool_calls list and has_tool_calls property."""

    def test_has_tool_calls_false_by_default(self) -> None:
        """has_tool_calls returns False when tool_calls is empty."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        assert msg.has_tool_calls is False

    def test_append_tool_call(self) -> None:
        """Appending a ToolCall to tool_calls makes has_tool_calls True."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        tc = ToolCall(
            id="tc1",
            function={"name": "Shell", "arguments": '{"cmd":"ls"}'},
        )
        msg.tool_calls.append(tc)
        assert msg.has_tool_calls is True
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].id == "tc1"

    def test_multiple_tool_calls(self) -> None:
        """Multiple tool calls can be appended."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        msg.tool_calls.append(ToolCall(id="tc1"))
        msg.tool_calls.append(ToolCall(id="tc2"))
        assert msg.has_tool_calls is True
        assert len(msg.tool_calls) == 2

    def test_has_tool_calls_after_clear(self) -> None:
        """has_tool_calls returns False after clearing tool_calls."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        msg.tool_calls.append(ToolCall(id="tc1"))
        assert msg.has_tool_calls is True
        msg.tool_calls.clear()
        assert msg.has_tool_calls is False


class TestMessageMarkComplete:
    """Tests for mark_complete()."""

    def test_mark_complete_changes_status(self) -> None:
        """mark_complete() transitions status from STREAMING to COMPLETE."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        assert msg.status == MessageStatus.STREAMING
        msg.mark_complete()
        assert msg.status == MessageStatus.COMPLETE

    def test_mark_complete_idempotent(self) -> None:
        """Calling mark_complete() twice is harmless."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        msg.mark_complete()
        msg.mark_complete()
        assert msg.status == MessageStatus.COMPLETE

    def test_mark_complete_on_user_message(self) -> None:
        """mark_complete() on an already-COMPLETE message is a no-op."""
        msg = Message.user_message(id="msg1", turn_id="t1", content="hey")
        assert msg.status == MessageStatus.COMPLETE
        msg.mark_complete()
        assert msg.status == MessageStatus.COMPLETE


class TestMessageSerialization:
    """Tests for Message model_dump / model_validate and round-trips."""

    def test_model_dump_returns_dict(self) -> None:
        """model_dump() returns a plain dict with enum values (not strings)."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        d = msg.model_dump()
        assert isinstance(d, dict)
        assert d["id"] == "msg1"
        assert d["role"] == MessageRole.ASSISTANT  # enum, not string
        assert d["status"] == MessageStatus.STREAMING

    def test_model_dump_json_mode(self) -> None:
        """model_dump(mode='json') returns JSON-safe dict with string enums."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        d = msg.model_dump(mode="json")
        assert isinstance(d, dict)
        assert d["role"] == "assistant"  # string, not enum
        assert d["status"] == "streaming"

    def test_model_validate_reconstructs(self) -> None:
        """model_validate(dict) reconstructs a Message."""
        data = {
            "id": "msg1",
            "turn_id": "t1",
            "role": "assistant",
            "status": "streaming",
            "content": "hello",
            "reasoning": "think",
            "tool_calls": [],
            "tool_result": "",
            "tool_call_id": "",
            "tool_name": "",
            "error": "",
        }
        msg = Message.model_validate(data)
        assert msg.id == "msg1"
        assert msg.role == MessageRole.ASSISTANT
        assert msg.status == MessageStatus.STREAMING
        assert msg.content == "hello"
        assert msg.reasoning == "think"

    def test_round_trip_model_dump(self) -> None:
        """model_dump() → model_validate produces equivalent Message."""
        original = Message.assistant_message(id="msg1", turn_id="t1")
        original.content = "hello"
        original.reasoning = "think"
        original.tool_calls.append(
            ToolCall(id="tc1", function={"name": "Shell", "arguments": '{"cmd":"ls"}'})
        )

        restored = Message.model_validate(original.model_dump())
        assert restored.id == original.id
        assert restored.turn_id == original.turn_id
        assert restored.role == original.role
        assert restored.status == original.status
        assert restored.content == original.content
        assert restored.reasoning == original.reasoning
        assert restored.tool_calls == original.tool_calls
        assert restored.has_tool_calls == original.has_tool_calls

    def test_round_trip_json_mode(self) -> None:
        """model_dump(mode='json') → model_validate produces equivalent Message."""
        original = Message.user_message(id="msg2", turn_id="t1", content="hi")
        restored = Message.model_validate(original.model_dump(mode="json"))
        assert restored.id == original.id
        assert restored.role == original.role
        assert restored.content == original.content


class TestMessageDefaultValues:
    """Tests that default values are empty strings/lists, not None."""

    def test_no_none_defaults_in_assistant_message(self) -> None:
        """All fields in a freshly-created assistant message are non-None."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        d = msg.model_dump()
        for key, value in d.items():
            assert value is not None, (
                f"Field '{key}' is None, expected empty string/list"
            )

    def test_content_defaults_to_empty_string(self) -> None:
        """content defaults to '' not None."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        assert msg.content == ""
        assert msg.content is not None

    def test_reasoning_defaults_to_empty_string(self) -> None:
        """reasoning defaults to '' not None."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        assert msg.reasoning == ""
        assert msg.reasoning is not None

    def test_tool_calls_defaults_to_empty_list(self) -> None:
        """tool_calls defaults to [] not None."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        assert msg.tool_calls == []
        assert msg.tool_calls is not None

    def test_tool_result_defaults_to_empty_string(self) -> None:
        """tool_result defaults to '' not None."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        assert msg.tool_result == ""
        assert msg.tool_result is not None

    def test_error_defaults_to_empty_string(self) -> None:
        """error defaults to '' not None."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        assert msg.error == ""
        assert msg.error is not None


class TestMessageRequiredFields:
    """Tests that id and turn_id are required."""

    def test_id_is_required(self) -> None:
        """Creating a Message without id raises ValidationError."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            Message(turn_id="t1")

    def test_turn_id_is_required(self) -> None:
        """Creating a Message without turn_id raises ValidationError."""
        with pytest.raises(Exception):
            Message(id="msg1")


# ═══════════════════════════════════════════════════════════════════════
# StreamEvent
# ═══════════════════════════════════════════════════════════════════════


class TestStreamEventFactories:
    """Tests for StreamEvent factory methods."""

    # ── message_start ──

    def test_message_start(self) -> None:
        """message_start() returns correct kind, message_id, turn_id."""
        ev = StreamEvent.message_start(turn_id="t1", message_id="msg1")
        assert ev.kind == StreamEventKind.MESSAGE_START
        assert ev.message_id == "msg1"
        assert ev.turn_id == "t1"
        # Other fields should be empty/default
        assert ev.field == ""
        assert ev.delta == ""
        assert ev.full_content == ""

    # ── chunk_delta ──

    def test_chunk_delta_content(self) -> None:
        """chunk_delta with field='content' and delta='hello'."""
        ev = StreamEvent.chunk_delta(
            message_id="msg1",
            field="content",
            delta="hello",
        )
        assert ev.kind == StreamEventKind.CHUNK_DELTA
        assert ev.message_id == "msg1"
        assert ev.field == "content"
        assert ev.delta == "hello"

    def test_chunk_delta_reasoning(self) -> None:
        """chunk_delta with field='reasoning' and delta='think'."""
        ev = StreamEvent.chunk_delta(
            message_id="msg1",
            field="reasoning",
            delta="think",
        )
        assert ev.kind == StreamEventKind.CHUNK_DELTA
        assert ev.field == "reasoning"
        assert ev.delta == "think"

    def test_chunk_delta_with_tool_name(self) -> None:
        """chunk_delta with optional tool_name."""
        ev = StreamEvent.chunk_delta(
            message_id="msg1",
            field="tool_calls",
            delta="Shell",
            tool_name="Shell",
        )
        assert ev.kind == StreamEventKind.CHUNK_DELTA
        assert ev.tool_name == "Shell"

    # ── chunk_complete ──

    def test_chunk_complete(self) -> None:
        """chunk_complete with full_content and tool metadata."""
        ev = StreamEvent.chunk_complete(
            message_id="msg1",
            field="tool_calls",
            full_content='{"cmd":"ls"}',
            tool_name="Shell",
        )
        assert ev.kind == StreamEventKind.CHUNK_COMPLETE
        assert ev.message_id == "msg1"
        assert ev.field == "tool_calls"
        assert ev.full_content == '{"cmd":"ls"}'
        assert ev.tool_name == "Shell"

    def test_chunk_complete_with_is_error(self) -> None:
        """chunk_complete can carry is_error flag."""
        ev = StreamEvent.chunk_complete(
            message_id="msg1",
            field="content",
            full_content="error text",
            is_error=True,
        )
        assert ev.kind == StreamEventKind.CHUNK_COMPLETE
        assert ev.is_error is True

    # ── message_finish ──

    def test_message_finish(self) -> None:
        """message_finish() returns MESSAGE_FINISH kind with message_id."""
        ev = StreamEvent.message_finish(message_id="msg1")
        assert ev.kind == StreamEventKind.MESSAGE_FINISH
        assert ev.message_id == "msg1"
        assert ev.turn_id == ""
        assert ev.field == ""
        assert ev.delta == ""

    # ── turn_complete ──

    def test_turn_complete_default_tokens(self) -> None:
        """turn_complete() with defaults: input_tokens=0, output_tokens=0."""
        ev = StreamEvent.turn_complete(turn_id="t1")
        assert ev.kind == StreamEventKind.TURN_COMPLETE
        assert ev.turn_id == "t1"
        assert ev.input_tokens == 0
        assert ev.output_tokens == 0

    def test_turn_complete_with_tokens(self) -> None:
        """turn_complete() with explicit token counts."""
        ev = StreamEvent.turn_complete(
            turn_id="t1",
            input_tokens=100,
            output_tokens=50,
        )
        assert ev.kind == StreamEventKind.TURN_COMPLETE
        assert ev.turn_id == "t1"
        assert ev.input_tokens == 100
        assert ev.output_tokens == 50

    # ── interrupted ──

    def test_interrupted(self) -> None:
        """interrupted() returns INTERRUPTED kind with reason."""
        ev = StreamEvent.interrupted(reason="user clicked stop")
        assert ev.kind == StreamEventKind.INTERRUPTED
        assert ev.reason == "user clicked stop"
        assert ev.message_id == ""
        assert ev.turn_id == ""

    def test_interrupted_empty_reason(self) -> None:
        """interrupted() with empty reason string."""
        ev = StreamEvent.interrupted(reason="")
        assert ev.kind == StreamEventKind.INTERRUPTED
        assert ev.reason == ""


class TestStreamEventKindEnum:
    """Verify each factory method sets the correct StreamEventKind."""

    def test_all_kinds_are_distinct(self) -> None:
        """All StreamEventKind values should be unique."""
        kinds = list(StreamEventKind)
        assert len(kinds) == len(set(kinds))

    def test_message_start_kind(self) -> None:
        ev = StreamEvent.message_start(turn_id="t1", message_id="m1")
        assert ev.kind == StreamEventKind.MESSAGE_START

    def test_chunk_delta_kind(self) -> None:
        ev = StreamEvent.chunk_delta(message_id="m1", field="c", delta="d")
        assert ev.kind == StreamEventKind.CHUNK_DELTA

    def test_chunk_complete_kind(self) -> None:
        ev = StreamEvent.chunk_complete(message_id="m1", field="c", full_content="fc")
        assert ev.kind == StreamEventKind.CHUNK_COMPLETE

    def test_message_finish_kind(self) -> None:
        ev = StreamEvent.message_finish(message_id="m1")
        assert ev.kind == StreamEventKind.MESSAGE_FINISH

    def test_turn_complete_kind(self) -> None:
        ev = StreamEvent.turn_complete(turn_id="t1")
        assert ev.kind == StreamEventKind.TURN_COMPLETE

    def test_interrupted_kind(self) -> None:
        ev = StreamEvent.interrupted(reason="stop")
        assert ev.kind == StreamEventKind.INTERRUPTED


class TestStreamEventSerialization:
    """Tests for StreamEvent model_dump / model_validate."""

    def test_model_dump_message_start(self) -> None:
        """model_dump() of message_start produces correct dict."""
        ev = StreamEvent.message_start(turn_id="t1", message_id="msg1")
        d = ev.model_dump()
        assert d["kind"] == StreamEventKind.MESSAGE_START
        assert d["message_id"] == "msg1"
        assert d["turn_id"] == "t1"

    def test_model_dump_json_mode(self) -> None:
        """model_dump(mode='json') produces JSON-safe string enums."""
        ev = StreamEvent.chunk_delta(message_id="msg1", field="content", delta="hello")
        d = ev.model_dump(mode="json")
        assert d["kind"] == "chunk_delta"  # string, not enum
        assert d["field"] == "content"
        assert d["delta"] == "hello"

    def test_model_validate_round_trip(self) -> None:
        """model_dump → model_validate round-trip for StreamEvent."""
        original = StreamEvent.turn_complete(
            turn_id="t1",
            input_tokens=42,
            output_tokens=7,
        )
        restored = StreamEvent.model_validate(original.model_dump())
        assert restored.kind == original.kind
        assert restored.turn_id == original.turn_id
        assert restored.input_tokens == original.input_tokens
        assert restored.output_tokens == original.output_tokens

    def test_interrupted_round_trip(self) -> None:
        """Round-trip for interrupted event."""
        original = StreamEvent.interrupted(reason="timeout")
        restored = StreamEvent.model_validate(original.model_dump())
        assert restored.kind == StreamEventKind.INTERRUPTED
        assert restored.reason == "timeout"


class TestStreamEventDefaultValues:
    """Tests that StreamEvent default values are empty/zero, not None."""

    def test_default_values_not_none(self) -> None:
        """All default fields should be non-None zero-ish values."""
        ev = StreamEvent.message_start(turn_id="t1", message_id="m1")
        assert ev.field is not None
        assert ev.delta is not None
        assert ev.full_content is not None
        assert ev.tool_name is not None
        assert ev.tool_args is not None
        assert ev.reason is not None
        assert ev.input_tokens is not None
        assert ev.output_tokens is not None
        assert ev.is_error is not None


# ═══════════════════════════════════════════════════════════════════════
# Turn
# ═══════════════════════════════════════════════════════════════════════


class TestTurn:
    """Tests for Turn — turn metadata."""

    def test_construction_with_id(self) -> None:
        """Turn(id='t1'): only id is required, remaining fields get defaults."""
        turn = Turn(id="t1")
        assert turn.id == "t1"
        assert turn.session_id == ""
        assert turn.model_id == ""
        assert turn.input_tokens == 0
        assert turn.output_tokens == 0
        assert turn.latency_ms == 0
        assert turn.created_at == ""

    def test_construction_full(self) -> None:
        """Turn with all fields set."""
        turn = Turn(
            id="t1",
            session_id="s1",
            model_id="deepseek-v3",
            input_tokens=100,
            output_tokens=50,
            latency_ms=320,
            created_at="2025-01-01T00:00:00Z",
        )
        assert turn.id == "t1"
        assert turn.session_id == "s1"
        assert turn.model_id == "deepseek-v3"
        assert turn.input_tokens == 100
        assert turn.output_tokens == 50
        assert turn.latency_ms == 320
        assert turn.created_at == "2025-01-01T00:00:00Z"

    def test_id_is_required(self) -> None:
        """Turn without id raises ValidationError."""
        with pytest.raises(Exception):
            Turn()

    def test_default_values_not_none(self) -> None:
        """All optional Turn fields default to empty strings or zero, not None."""
        turn = Turn(id="t1")
        assert turn.session_id is not None
        assert turn.model_id is not None
        assert turn.created_at is not None
        assert turn.input_tokens is not None
        assert turn.output_tokens is not None
        assert turn.latency_ms is not None

    def test_model_dump(self) -> None:
        """model_dump() returns correct dict."""
        turn = Turn(id="t1", session_id="s1", input_tokens=10)
        d = turn.model_dump()
        assert d["id"] == "t1"
        assert d["session_id"] == "s1"
        assert d["input_tokens"] == 10
        assert d["output_tokens"] == 0

    def test_model_validate_round_trip(self) -> None:
        """model_dump → model_validate round-trip for Turn."""
        original = Turn(
            id="t1",
            session_id="s1",
            model_id="m1",
            input_tokens=10,
            output_tokens=5,
            latency_ms=100,
            created_at="now",
        )
        restored = Turn.model_validate(original.model_dump())
        assert restored.id == original.id
        assert restored.session_id == original.session_id
        assert restored.model_id == original.model_id
        assert restored.input_tokens == original.input_tokens
        assert restored.output_tokens == original.output_tokens
        assert restored.latency_ms == original.latency_ms
        assert restored.created_at == original.created_at


# ═══════════════════════════════════════════════════════════════════════
# Cross-type integration tests
# ═══════════════════════════════════════════════════════════════════════


class TestIntegrationMessageAndToolCall:
    """Integration tests: Message with embedded ToolCalls."""

    def test_message_with_tool_calls_serializes_correctly(self) -> None:
        """A Message with tool_calls serializes/deserializes correctly."""
        msg = Message.assistant_message(id="msg1", turn_id="t1")
        msg.tool_calls.append(
            ToolCall(
                id="tc1",
                function={"name": "Shell", "arguments": '{"cmd":"ls"}'},
            )
        )
        msg.tool_calls.append(
            ToolCall(
                id="tc2",
                function={"name": "Read", "arguments": '{"path":"/f"}'},
            )
        )

        d = msg.model_dump(mode="json")
        assert len(d["tool_calls"]) == 2
        assert d["tool_calls"][0]["id"] == "tc1"
        assert d["tool_calls"][0]["function"]["name"] == "Shell"
        assert d["tool_calls"][1]["id"] == "tc2"

        # Round-trip
        restored = Message.model_validate(d)
        assert restored.has_tool_calls is True
        assert len(restored.tool_calls) == 2
        assert restored.tool_calls[0].id == "tc1"
        assert restored.tool_calls[1].id == "tc2"

    def test_tool_message_and_tool_call_correlation(self) -> None:
        """A tool_message references a tool_call via tool_call_id."""
        tool_msg = Message.tool_message(
            id="msg_tool",
            turn_id="t1",
            tool_call_id="tc_abc",
            tool_name="Shell",
            result="file.txt",
        )
        assert tool_msg.tool_call_id == "tc_abc"
        assert tool_msg.tool_name == "Shell"

        # The tool_call_id would match a ToolCall.id from an earlier message
        d = tool_msg.model_dump(mode="json")
        assert d["tool_call_id"] == "tc_abc"
        assert d["tool_name"] == "Shell"
        assert d["tool_result"] == "file.txt"


class TestIntegrationStreamEventMimicsSSEProtocol:
    """Tests that verify StreamEvent field names match Message attribute names."""

    def test_chunk_delta_field_is_message_attribute(self) -> None:
        """StreamEvent.field should be a valid Message attribute for += mirroring."""
        msg = Message.assistant_message(id="m1", turn_id="t1")

        # Simulate SSE: frontend receives chunk_delta events and does msg[field] += delta
        events = [
            StreamEvent.chunk_delta(message_id="m1", field="content", delta="Hello"),
            StreamEvent.chunk_delta(message_id="m1", field="content", delta=" "),
            StreamEvent.chunk_delta(message_id="m1", field="content", delta="World"),
            StreamEvent.chunk_delta(
                message_id="m1", field="reasoning", delta="I think"
            ),
        ]

        for ev in events:
            # This is what the frontend does: msg[ev.field] += ev.delta
            current = getattr(msg, ev.field)
            setattr(msg, ev.field, current + ev.delta)

        assert msg.content == "Hello World"
        assert msg.reasoning == "I think"
