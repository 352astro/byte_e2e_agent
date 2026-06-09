import tempfile
import uuid

import pytest

from agent.core.config import SessionConfig
from agent.core.workspace import Workspace
from agent.runtime.turn_context_updates import (
    count_turns_since_last_task_tool,
    plan_context_updates,
    plan_skills_update,
    plan_task_update,
)
from agent.session import load_session, write_session_prefix
from agent.tools.skill import skill_context_message
from shared.hooks import BaseHook, HookManager
from shared.types import Message


def test_skills_update_does_not_duplicate_legacy_prefix() -> None:
    history = [skill_context_message()]

    update = plan_skills_update(history)

    assert update is None


def test_task_list_counts_as_task_activity() -> None:
    history = [
        {"role": "user", "content": "one"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "tc1",
                    "type": "function",
                    "function": {"name": "TaskList", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "tc1", "content": "[]"},
        {"role": "user", "content": "two"},
    ]

    assert count_turns_since_last_task_tool(history) == 1


def test_task_update_is_deduped() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Workspace(tmpdir, workspace_uuid=f"ctx-update-{uuid.uuid4().hex}")
        sid = "taskdedupe"
        ws.ensure_dirs(sid)
        ws.tasks_path(sid).write_text(
            '[{"id":"t1","name":"Do it","description":"Do it",'
            '"status":"pending","depends_on":[],"summary":""}]\n',
            encoding="utf-8",
        )
        history = [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "two"},
        ]
        update = plan_task_update(history, workspace=ws, session_id=sid)
        assert update is not None

        deduped = plan_task_update(
            [*history, {"role": "system", "content": update.content}],
            workspace=ws,
            session_id=sid,
        )
        assert deduped is None


@pytest.mark.asyncio
async def test_context_updates_wrap_hook_system_context() -> None:
    class MemoryHook(BaseHook):
        async def on_context_assemble(self, **kwargs):
            return [{"role": "system", "content": "## Long-term Memory\nFact:\n- Use pytest."}]

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Workspace(tmpdir, workspace_uuid=f"ctx-plan-{uuid.uuid4().hex}")
        sid = "memoryctx"
        write_session_prefix(ws, sid, SessionConfig.user_main("main", "model"))
        user = Message.user_message("u1", "turn1", "check tests")
        from agent.session.session import _save_message_sync

        _save_message_sync(ws, sid, user)

        updates = await plan_context_updates(
            hooks=HookManager([MemoryHook()]),
            session_id=sid,
            turn_id="turn1",
            workspace=ws,
            user_question="check tests",
        )

    assert len(updates) == 1
    assert updates[0].kind == "Long-term Memory"
    assert updates[0].content.startswith("## Context Update: Long-term Memory")
    assert "immediately preceding user request" in updates[0].content


def test_write_session_prefix_uses_assigned_task_separately_from_rules() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Workspace(tmpdir, workspace_uuid=f"assigned-task-{uuid.uuid4().hex}")
        sid = "subagenttask"
        config = SessionConfig.subagent(
            parent_id="parent",
            name="child",
            task="Inspect the payment flow.",
            model_id="model",
        )

        write_session_prefix(ws, sid, config)
        context = load_session(sid, workspace=ws).get_llm_context()

    assigned = [m for m in context if m["role"] == "system" and "## Assigned Task" in m["content"]]
    rules = [m for m in context if m["role"] == "system" and "## Session Rules" in m["content"]]
    assert len(assigned) == 1
    assert "Inspect the payment flow." in assigned[0]["content"]
    assert rules == []
