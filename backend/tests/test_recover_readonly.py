from __future__ import annotations

import json

from app.schemas.session import CreateSessionRequest
from app.services.chat_service import ChatService
from app.services.session_service import SessionService
from app.services.workspace_context import WorkspaceContext
from shared.types import Message, ToolCall, ToolCallFunction


def test_recover_running_session_does_not_repair_unpaired_tool_call(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ctx = WorkspaceContext(str(workspace), str(tmp_path / "metrics.sqlite3"))
    service = SessionService(ctx)
    session_id = service.create_session(CreateSessionRequest(name="main"))["session_id"]
    assistant = Message.assistant_message("assistant-1", "turn-1")
    assistant.tool_calls = [
        ToolCall(
            id="tool-1",
            function=ToolCallFunction(name="Read", arguments='{"path":"a.txt"}'),
        )
    ]
    assistant.mark_complete()
    messages_path = ctx.messages_path(session_id)
    messages_path.write_text(
        json.dumps(
            assistant.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    ctx.runtime._begin_run(ctx.create_runtime_session_entry(session_id))

    state = service.get_recovery_state(session_id)

    assert state["session_running"] is True
    assert len(state["messages"]) == 1
    assert messages_path.read_text(encoding="utf-8").count("\n") == 1


def test_recover_does_not_repair_when_workspace_runtime_busy_with_other_session(
    tmp_path,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ctx = WorkspaceContext(str(workspace), str(tmp_path / "metrics.sqlite3"))
    service = SessionService(ctx)
    parent_id = service.create_session(CreateSessionRequest(name="parent"))["session_id"]
    child_id = service.create_session(CreateSessionRequest(name="child"))["session_id"]
    assistant = Message.assistant_message("assistant-1", "turn-1")
    assistant.tool_calls = [
        ToolCall(
            id="tool-1",
            function=ToolCallFunction(name="SubAgent", arguments='{"prompt":"x"}'),
        )
    ]
    assistant.mark_complete()
    messages_path = ctx.messages_path(parent_id)
    messages_path.write_text(
        json.dumps(
            assistant.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    ctx.runtime._begin_run(ctx.create_runtime_session_entry(child_id))

    state = service.get_recovery_state(parent_id)

    assert state["session_running"] is False
    assert state["runtime_busy"] is True
    assert len(state["messages"]) == 1
    assert messages_path.read_text(encoding="utf-8").count("\n") == 1


def test_stream_replay_does_not_repair_when_workspace_runtime_busy(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ctx = WorkspaceContext(str(workspace), str(tmp_path / "metrics.sqlite3"))
    service = SessionService(ctx)
    session_id = service.create_session(CreateSessionRequest(name="main"))["session_id"]
    assistant = Message.assistant_message("assistant-1", "turn-1")
    assistant.tool_calls = [
        ToolCall(
            id="tool-1",
            function=ToolCallFunction(name="Read", arguments='{"path":"a.txt"}'),
        )
    ]
    assistant.mark_complete()
    messages_path = ctx.messages_path(session_id)
    messages_path.write_text(
        json.dumps(
            assistant.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    ctx.runtime._begin_run(ctx.create_runtime_session_entry(session_id))

    stream = ChatService(ctx).get_stream(session_id)

    assert len(stream.messages) == 1
    assert messages_path.read_text(encoding="utf-8").count("\n") == 1
