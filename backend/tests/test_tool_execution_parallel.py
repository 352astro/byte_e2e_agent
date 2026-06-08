from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import patch

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agent.core.workspace import Workspace
from agent.tool_execution import execute_tool_calls
from agent.tools import tool_registry
from agent.tools.registry import ToolRegistry
from agent.tools.toolset import ToolSet
from shared.hooks import BaseHook, HookManager
from shared.types import Message, ToolCall, ToolCallFunction


class DelayInput(BaseModel):
    label: str = Field(...)
    delay_ms: int = Field(default=0)


def _tool_call(tool_id: str, name: str, label: str, delay_ms: int = 0) -> ToolCall:
    return ToolCall(
        id=tool_id,
        function=ToolCallFunction(
            name=name,
            arguments=json.dumps({"label": label, "delay_ms": delay_ms}),
        ),
    )


def _browser_inspect_call(tool_id: str, prompt: str, delay_ms: int = 0) -> ToolCall:
    return ToolCall(
        id=tool_id,
        function=ToolCallFunction(
            name="BrowserInspect",
            arguments=json.dumps(
                {
                    "url": "http://example.com",
                    "prompt": prompt,
                    "max_steps": 1,
                    "delay_ms": delay_ms,
                }
            ),
        ),
    )


def _toolset(*names: str) -> ToolSet:
    registry = ToolRegistry()

    async def handler(label: str, delay_ms: int = 0, **kwargs) -> str:
        await asyncio.sleep(delay_ms / 1000)
        return label

    for name in names:
        registry.register(
            StructuredTool.from_function(
                coroutine=handler,
                name=name,
                description=f"Fake {name}",
                args_schema=DelayInput,
            )
        )
    return ToolSet(registry)


def _workspace(path) -> Workspace:
    return Workspace(path, workspace_uuid="test-workspace")


class CaptureHook(BaseHook):
    def __init__(self) -> None:
        self.results: list[tuple[str, str]] = []

    async def on_chunk_complete(self, *, msg: Message, field: str, **kwargs):
        if field == "tool_result":
            self.results.append((msg.tool_call_id, msg.tool_result))


async def _allow_guard(*args, **kwargs) -> bool:
    return True


async def _invoke_subagent(**kwargs) -> str:
    return "subagent"


async def _request_human_input(*args, **kwargs) -> dict:
    return {}


@pytest.mark.asyncio
async def test_read_tools_run_in_parallel(tmp_path):
    msg = Message.assistant_message("assistant", "turn")
    msg.tool_calls = [
        _tool_call("tc-read", "Read", "read", delay_ms=180),
        _tool_call("tc-grep", "Grep", "grep", delay_ms=180),
    ]
    capture = CaptureHook()

    start = time.perf_counter()
    await execute_tool_calls(
        assistant_msg=msg,
        ws=_workspace(tmp_path),
        toolset=_toolset("Read", "Grep"),
        interrupt_event=asyncio.Event(),
        session_id="sid",
        turn_id="turn",
        hook_manager=HookManager([capture]),
        ask_guard=_allow_guard,
        invoke_subagent=_invoke_subagent,
        request_human_input=_request_human_input,
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 0.30
    assert sorted(capture.results) == [("tc-grep", "grep"), ("tc-read", "read")]


@pytest.mark.asyncio
async def test_barrier_tool_splits_parallel_batches(tmp_path):
    msg = Message.assistant_message("assistant", "turn")
    msg.tool_calls = [
        _tool_call("tc-read", "Read", "read", delay_ms=120),
        _tool_call("tc-shell", "Shell", "shell", delay_ms=120),
        _tool_call("tc-grep", "Grep", "grep", delay_ms=120),
    ]
    capture = CaptureHook()

    start = time.perf_counter()
    await execute_tool_calls(
        assistant_msg=msg,
        ws=_workspace(tmp_path),
        toolset=_toolset("Read", "Shell", "Grep"),
        interrupt_event=asyncio.Event(),
        session_id="sid",
        turn_id="turn",
        hook_manager=HookManager([capture]),
        ask_guard=_allow_guard,
        invoke_subagent=_invoke_subagent,
        request_human_input=_request_human_input,
    )
    elapsed = time.perf_counter() - start

    assert elapsed >= 0.34
    assert capture.results == [
        ("tc-read", "read"),
        ("tc-shell", "shell"),
        ("tc-grep", "grep"),
    ]


@pytest.mark.asyncio
async def test_browser_inspect_tools_run_in_parallel(tmp_path):
    msg = Message.assistant_message("assistant", "turn")
    msg.tool_calls = [
        _browser_inspect_call("tc-browser-a", "inspect a", delay_ms=180),
        _browser_inspect_call("tc-browser-b", "inspect b", delay_ms=180),
    ]
    capture = CaptureHook()

    async def fake_browser_inspect(*, prompt: str, **kwargs):
        await asyncio.sleep(0.18)
        return prompt

    with patch("agent.runtime.subagents.run_subagent") as standalone_run_subagent:
        start = time.perf_counter()
        await execute_tool_calls(
            assistant_msg=msg,
            ws=_workspace(tmp_path),
            toolset=ToolSet(tool_registry, "BrowserInspect"),
            interrupt_event=asyncio.Event(),
            session_id="sid",
            turn_id="turn",
            hook_manager=HookManager([capture]),
            ask_guard=_allow_guard,
            invoke_subagent=_invoke_subagent,
            invoke_browser_inspect=fake_browser_inspect,
            request_human_input=_request_human_input,
        )
        elapsed = time.perf_counter() - start

    assert elapsed < 0.30
    standalone_run_subagent.assert_not_called()
    assert sorted(capture.results) == [
        ("tc-browser-a", "inspect a"),
        ("tc-browser-b", "inspect b"),
    ]
