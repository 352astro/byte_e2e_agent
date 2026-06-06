"""Tests for repaired OpenAI context projection from partial Message history."""

import os
from pathlib import Path

import pytest

from agent.session._data import _build_llm_context
from shared.types import Message, MessageStatus, ToolCall, ToolCallFunction


def _assistant(mid: str = "a1") -> Message:
    return Message.assistant_message(mid, "t1")


def test_empty_assistant_is_synthesized() -> None:
    msg = _assistant()

    context = _build_llm_context([msg])

    assert context == [
        {
            "role": "assistant",
            "content": ("[History repair] Interrupted before producing visible output."),
        }
    ]


def test_reasoning_only_assistant_is_synthesized() -> None:
    msg = _assistant()
    msg.reasoning = "private reasoning"

    context = _build_llm_context([msg])

    assert context == [
        {
            "role": "assistant",
            "content": (
                "[History repair] Interrupted during reasoning before producing visible output."
            ),
        }
    ]


def test_partial_content_assistant_is_kept_with_interrupted_marker() -> None:
    msg = _assistant()
    msg.content = "partial answer"
    msg.status = MessageStatus.STREAMING

    context = _build_llm_context([msg])

    assert context == [
        {
            "role": "assistant",
            "content": ("partial answer\n\n[History repair] Interrupted before completion."),
        }
    ]


def test_unpaired_valid_tool_call_gets_synthetic_tool_result() -> None:
    msg = _assistant()
    msg.tool_calls = [
        ToolCall(
            id="tc1",
            function=ToolCallFunction(name="Shell", arguments='{"command":"pwd"}'),
        )
    ]

    context = _build_llm_context([msg])

    assert context[0]["role"] == "assistant"
    assert context[0]["tool_calls"][0]["id"] == "tc1"
    assert context[1] == {
        "role": "tool",
        "tool_call_id": "tc1",
        "content": "Error: The interrupted tool call for Shell did not complete.",
    }


def test_malformed_tool_call_is_omitted_with_system_synthesis() -> None:
    msg = _assistant()
    msg.tool_calls = [
        ToolCall(
            id="tc-bad",
            function=ToolCallFunction(name="Shell", arguments='{"command":'),
        )
    ]

    context = _build_llm_context([msg])

    assert context[0]["role"] == "system"
    assert "Omitted malformed assistant tool call" in context[0]["content"]
    assert context[1]["role"] == "assistant"
    assert "Interrupted before producing visible output" in context[1]["content"]
    assert all("tool_calls" not in item for item in context)


def test_orphan_tool_result_is_synthesized_as_system_note() -> None:
    msg = Message.tool_message(
        id="tool1",
        turn_id="t1",
        tool_call_id="missing",
        tool_name="Shell",
        result="late result",
    )

    context = _build_llm_context([msg])

    assert context == [
        {
            "role": "system",
            "content": ("[History repair] Omitted orphaned tool result for tool_call_id=missing."),
        }
    ]


def test_mixed_valid_and_invalid_tool_calls_keep_valid_sequence() -> None:
    msg = _assistant()
    msg.tool_calls = [
        ToolCall(
            id="",
            function=ToolCallFunction(name="Bad", arguments="{}"),
        ),
        ToolCall(
            id="tc1",
            function=ToolCallFunction(name="Shell", arguments='{"command":"pwd"}'),
        ),
    ]

    context = _build_llm_context([msg])

    assert context[0]["role"] == "system"
    assert context[1]["role"] == "assistant"
    assert len(context[1]["tool_calls"]) == 1
    assert context[1]["tool_calls"][0]["id"] == "tc1"
    assert context[2]["role"] == "tool"
    assert context[2]["tool_call_id"] == "tc1"


def _load_dotenv() -> dict[str, str]:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@pytest.mark.skipif(
    os.environ.get("RUN_LLM_CONTEXT_CONTRACT") != "1",
    reason="set RUN_LLM_CONTEXT_CONTRACT=1 to call the real model API",
)
def test_repaired_contexts_are_accepted_by_real_model() -> None:
    dotenv = _load_dotenv()
    api_key = os.environ.get("LLM_API_KEY") or dotenv.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL") or dotenv.get("LLM_BASE_URL")
    model = os.environ.get("LLM_MODEL_ID") or dotenv.get("LLM_MODEL_ID")
    if not api_key or not base_url or not model:
        pytest.skip("LLM_API_KEY, LLM_BASE_URL, and LLM_MODEL_ID are required")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    cases: list[list[Message]] = []

    empty = _assistant("empty")
    cases.append([Message.user_message("u1", "t1", "continue"), empty])

    reasoning = _assistant("reasoning")
    reasoning.reasoning = "thinking"
    cases.append([Message.user_message("u2", "t2", "continue"), reasoning])

    partial = _assistant("partial")
    partial.content = "partial answer"
    cases.append([Message.user_message("u3", "t3", "continue"), partial])

    tool = _assistant("tool")
    tool.tool_calls = [
        ToolCall(
            id="tc1",
            function=ToolCallFunction(name="Shell", arguments='{"command":"pwd"}'),
        )
    ]
    cases.append([Message.user_message("u4", "t4", "continue"), tool])

    malformed = _assistant("malformed")
    malformed.tool_calls = [
        ToolCall(
            id="tc-bad",
            function=ToolCallFunction(name="Shell", arguments='{"command":'),
        )
    ]
    cases.append([Message.user_message("u5", "t5", "continue"), malformed])

    for messages in cases:
        repaired = _build_llm_context(messages)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Reply with OK."},
                *repaired,
                {"role": "user", "content": "OK?"},
            ],
            max_tokens=4,
            temperature=0,
        )
        assert resp.choices
