"""Tests for the current OpenAI streaming action primitives."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.actions import execute_one_tool, model_call, run_subagent
from agent.core.workspace import Workspace
from agent.errors import InterruptedError
from agent.tools import tool_registry
from agent.tools.toolset import ToolSet
from shared.hooks import HookManager


def _chunk(
    *,
    content: str = "",
    reasoning: str = "",
    tool_calls: list | None = None,
    finish_reason: str = "",
    usage=None,
):
    delta = SimpleNamespace(
        content=content or None,
        reasoning_content=reasoning or None,
        tool_calls=tool_calls or [],
    )
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason or None)
    return SimpleNamespace(choices=[choice], usage=usage)


def _tool_delta(
    *,
    index: int = 0,
    id: str = "",
    name: str = "",
    arguments: str = "",
):
    return SimpleNamespace(
        index=index,
        id=id or None,
        function=SimpleNamespace(name=name or None, arguments=arguments or None),
    )


def _client_with_chunks(chunks: list):
    client = MagicMock()
    client.chat.completions.create.return_value = chunks
    return client


class TestModelCall:
    @pytest.mark.asyncio
    async def test_streams_content_reasoning_and_finish_reason(self):
        client = _client_with_chunks(
            [
                _chunk(reasoning="think "),
                _chunk(content="answer", finish_reason="stop"),
            ]
        )
        hooks = AsyncMock(spec=HookManager)
        interrupt_event = asyncio.Event()

        msg, finish_reason = await model_call(
            client,
            "test-model",
            "s1",
            [{"role": "user", "content": "q"}],
            [],
            "m1",
            turn_id="t1",
            interrupt_event=interrupt_event,
            hook_manager=hooks,
        )

        assert finish_reason == "stop"
        assert msg.content == "answer"
        assert msg.reasoning == "think "
        hooks.on_chunk_delta.assert_any_call(
            msg=msg, field="reasoning", delta="think "
        )
        hooks.on_chunk_delta.assert_any_call(
            msg=msg, field="content", delta="answer"
        )

    @pytest.mark.asyncio
    async def test_streams_tool_calls(self):
        client = _client_with_chunks(
            [
                _chunk(
                    tool_calls=[
                        _tool_delta(index=0, id="tc1", name="Shell"),
                        _tool_delta(index=0, arguments='{"command":"pwd"}'),
                    ],
                    finish_reason="tool_calls",
                )
            ]
        )
        hooks = AsyncMock(spec=HookManager)
        interrupt_event = asyncio.Event()

        msg, finish_reason = await model_call(
            client,
            "test-model",
            "s1",
            [{"role": "user", "content": "q"}],
            [{"type": "function", "function": {"name": "Shell"}}],
            "m1",
            turn_id="t1",
            interrupt_event=interrupt_event,
            hook_manager=hooks,
        )

        assert finish_reason == "tool_calls"
        assert msg.tool_calls[0].id == "tc1"
        assert msg.tool_calls[0].function.name == "Shell"
        assert msg.tool_calls[0].function.arguments == '{"command":"pwd"}'

    @pytest.mark.asyncio
    async def test_interrupt_raises_during_stream(self):
        client = _client_with_chunks([_chunk(content="hello")])
        interrupt_event = asyncio.Event()
        interrupt_event.set()

        with pytest.raises(InterruptedError, match="Interrupted during LLM call"):
            await model_call(
                client,
                "test-model",
                "s1",
                [{"role": "user", "content": "q"}],
                [],
                "m1",
                interrupt_event=interrupt_event,
            )


class TestExecuteOneTool:
    @pytest.mark.asyncio
    async def test_interrupt_before_execution_raises(self):
        ws = MagicMock(spec=Workspace)
        toolset = ToolSet(tool_registry, "Shell")
        interrupt_event = asyncio.Event()
        interrupt_event.set()

        with pytest.raises(InterruptedError, match="Interrupted before tool execution"):
            await execute_one_tool(
                {"function": {"name": "Shell", "arguments": '{"command":"pwd"}'}},
                ws,
                toolset,
                interrupt_event=interrupt_event,
            )

    @pytest.mark.asyncio
    async def test_shell_executes_in_workspace(self, tmp_path):
        ws = Workspace(tmp_path)
        toolset = ToolSet(tool_registry, "Shell")
        interrupt_event = asyncio.Event()

        result = await execute_one_tool(
            {"function": {"name": "Shell", "arguments": '{"command":"pwd"}'}},
            ws,
            toolset,
            interrupt_event=interrupt_event,
        )

        assert str(tmp_path) in result

    @pytest.mark.asyncio
    async def test_subagent_dispatch_preserves_interrupt_event(self):
        ws = MagicMock(spec=Workspace)
        toolset = ToolSet(tool_registry, "SubAgent", "Shell")
        interrupt_event = asyncio.Event()

        with patch("agent.actions.run_subagent", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "subagent result"
            result = await execute_one_tool(
                {
                    "function": {
                        "name": "SubAgent",
                        "arguments": '{"prompt":"do it","max_steps":2}',
                    }
                },
                ws,
                toolset,
                interrupt_event=interrupt_event,
                session_id="s1",
            )

        assert result == "subagent result"
        assert mock_run.call_args.kwargs["interrupt_event"] is interrupt_event


class TestRunSubagent:
    @pytest.mark.asyncio
    async def test_returns_immediately_when_interrupted_before_first_step(self):
        ws = MagicMock(spec=Workspace)
        toolset = ToolSet(tool_registry, "Shell")
        interrupt_event = asyncio.Event()
        interrupt_event.set()

        result = await run_subagent(
            ws,
            toolset,
            "task",
            3,
            openai_client=MagicMock(),
            model_id="test-model",
            session_id="s1",
            interrupt_event=interrupt_event,
        )

        assert result == "SubAgent completed (no output)."
