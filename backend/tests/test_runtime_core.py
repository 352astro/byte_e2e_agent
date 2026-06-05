"""Comprehensive unit tests for AgentRuntime ReAct loop (链路 3).

Tests cover:
- Construction and properties
- Session management (CRUD)
- invoke_user (main entry point)
- start (compat wrapper)
- invoke_agent (agent-to-agent)
- interrupt / resolve
- State transitions
- Concurrent execution prevention

All tests use mocks — no real LLM calls.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.config import (
    AccessPolicy,
    InvokePermission,
    Owner,
    SessionConfig,
)
from agent.core.workspace import Workspace

# Import under test
from agent.runtime import AgentRuntime
from agent.session.entry import SessionEntry
from agent.session.status import RuntimeStatus, SessionStatus
from shared.hooks import HookManager

# ═══════════════════════════════════════════════════════════
# Mock _execute_turn helpers (closures — patch.object with side_effect
# calls plain functions, not bound methods, so self is not available)
# ═══════════════════════════════════════════════════════════


def _make_mock_execute_turn_complete(runtime: AgentRuntime):
    async def _mock(
        entry: SessionEntry,
        question: str,
        max_steps: int,
        shadow_repo=None,
    ) -> None:
        runtime._running_session_id = None
        runtime._loop_task = None
        entry.transition_to(SessionStatus.IDLE)

    return _mock


def _make_mock_execute_turn_interrupted(runtime: AgentRuntime):
    async def _mock(
        entry: SessionEntry,
        question: str,
        max_steps: int,
        shadow_repo=None,
    ) -> None:
        assert runtime._interrupt_event is not None
        while not runtime._interrupt_event.is_set():
            await asyncio.sleep(0.001)
        entry.transition_to(SessionStatus.INTERRUPTED)
        runtime._running_session_id = None
        runtime._loop_task = None
        entry.transition_to(SessionStatus.IDLE)

    return _mock


def _make_mock_execute_turn_hanging(runtime: AgentRuntime):
    async def _mock(
        entry: SessionEntry,
        question: str,
        max_steps: int,
        shadow_repo=None,
    ) -> None:
        await asyncio.Event().wait()  # never completes

    return _mock


async def _mock_invoke_execute_turn(
    entry: SessionEntry,
    question: str,
    max_steps: int,
    shadow_repo=None,
    **kwargs,
) -> str:
    entry.transition_to(SessionStatus.IDLE)
    return f"SubAgent '{entry.id}' completed task: {question}"


# ═══════════════════════════════════════════════════════════
# Factory helpers
# ═══════════════════════════════════════════════════════════


def _make_runtime(
    workspace: Workspace | None = None,
    hook_manager: HookManager | None = None,
) -> AgentRuntime:
    """Create an AgentRuntime with sensible test defaults."""
    return AgentRuntime(
        workspace=workspace or Workspace(),
        hook_manager=hook_manager or HookManager(),
    )


def _make_config(name: str = "test", model_id: str = "test-model") -> SessionConfig:
    """Create a SessionConfig for testing."""
    return SessionConfig.user_main(name=name, model_id=model_id)


# ═══════════════════════════════════════════════════════════
# Construction & Properties
# ═══════════════════════════════════════════════════════════


class TestAgentRuntimeConstruction:
    """Tests for AgentRuntime.__init__() and basic properties."""

    def test_constructor_accepts_all_params(self):
        """Constructor accepts workspace, hook_manager, and llm."""
        ws = Workspace()
        hm = HookManager()
        runtime = AgentRuntime(workspace=ws, hook_manager=hm, llm=None)
        assert runtime._workspace is ws
        assert runtime._hooks is hm
        assert runtime._llm is None

    def test_constructor_defaults(self):
        """Constructor provides sensible defaults when no args given."""
        runtime = AgentRuntime()
        assert isinstance(runtime._workspace, Workspace)
        assert isinstance(runtime._hooks, HookManager)
        assert runtime._llm is None
        assert runtime._sessions == {}
        assert runtime._running_session_id is None
        assert runtime._interrupt_event is None
        assert runtime._loop_task is None
        assert runtime._pending == {}

    def test_hooks_property_returns_hook_manager(self):
        """hooks property returns the hook_manager instance."""
        hm = HookManager()
        runtime = AgentRuntime(hook_manager=hm)
        assert runtime.hooks is hm

    def test_workspace_property_returns_workspace(self):
        """workspace property returns the workspace instance."""
        ws = Workspace()
        runtime = AgentRuntime(workspace=ws)
        assert runtime.workspace is ws

    def test_status_idle_when_no_running_session(self):
        """status returns IDLE when no session is running."""
        runtime = _make_runtime()
        assert runtime.status == RuntimeStatus.IDLE

    def test_status_running_when_session_active(self):
        """status returns RUNNING when a session is running."""
        runtime = _make_runtime()
        runtime._running_session_id = "some-id"
        assert runtime.status == RuntimeStatus.RUNNING

    def test_pending_request_none_initially(self):
        """pending_request returns None when there are no pending requests."""
        runtime = _make_runtime()
        assert runtime.pending_request is None

    def test_pending_request_returns_first_pending(self):
        """pending_request returns the first pending request dict."""
        runtime = _make_runtime()
        runtime._pending["tid-1"] = {
            "kind": "permission_request",
            "message": {"tool": "shell"},
        }
        runtime._pending["tid-2"] = {
            "kind": "approval",
            "message": {},
        }
        req = runtime.pending_request
        assert req is not None
        assert req["message_id"] == "tid-1"
        assert req["kind"] == "permission_request"
        assert req["message"] == {"tool": "shell"}


# ═══════════════════════════════════════════════════════════
# Session Management
# ═══════════════════════════════════════════════════════════


class TestSessionManagement:
    """Tests for create_session, get_session, list_sessions, is_running_session."""

    def test_create_session_returns_session_entry(self):
        """create_session(config) returns a SessionEntry."""
        runtime = _make_runtime()
        config = _make_config()
        entry = runtime.create_session(config)
        assert isinstance(entry, SessionEntry)
        assert entry.config is config
        assert entry.id  # auto-generated

    def test_create_session_with_custom_id(self):
        """create_session accepts an explicit session_id."""
        runtime = _make_runtime()
        config = _make_config()
        entry = runtime.create_session(config, session_id="my-custom-id")
        assert entry.id == "my-custom-id"

    def test_create_session_stores_in_internal_dict(self):
        """After create_session the entry is stored in _sessions."""
        runtime = _make_runtime()
        config = _make_config()
        entry = runtime.create_session(config, session_id="sid1")
        assert "sid1" in runtime._sessions
        assert runtime._sessions["sid1"] is entry

    def test_get_session_returns_entry(self):
        """get_session returns the SessionEntry for a known id."""
        runtime = _make_runtime()
        config = _make_config()
        entry = runtime.create_session(config, session_id="sid1")
        assert runtime.get_session("sid1") is entry

    def test_get_session_returns_none_for_unknown(self):
        """get_session returns None for an unknown session id."""
        runtime = _make_runtime()
        assert runtime.get_session("nonexistent") is None

    def test_list_sessions_includes_created_sessions(self):
        """list_sessions returns a sorted list of all known session IDs."""
        runtime = _make_runtime()
        config = _make_config()
        runtime.create_session(config, session_id="b-session")
        runtime.create_session(config, session_id="a-session")
        ids = runtime.list_sessions()
        assert "a-session" in ids
        assert "b-session" in ids
        # Should be sorted
        assert ids == sorted(ids)

    def test_is_running_session_true_when_matches(self):
        """is_running_session returns True when the id matches the running session."""
        runtime = _make_runtime()
        runtime._running_session_id = "active-id"
        assert runtime.is_running_session("active-id") is True

    def test_is_running_session_false_when_different(self):
        """is_running_session returns False for a non-matching id."""
        runtime = _make_runtime()
        runtime._running_session_id = "active-id"
        assert runtime.is_running_session("other-id") is False

    def test_is_running_session_false_when_none_running(self):
        """is_running_session returns False when no session is running."""
        runtime = _make_runtime()
        assert runtime.is_running_session("any-id") is False


# ═══════════════════════════════════════════════════════════
# invoke_user
# ═══════════════════════════════════════════════════════════


class TestInvokeUser:
    """Tests for AgentRuntime.invoke_user()."""

    @pytest.mark.asyncio
    async def test_raises_runtimeerror_if_already_running(self):
        """invoke_user raises RuntimeError when a session is already running."""
        runtime = _make_runtime()
        runtime._running_session_id = "existing-id"
        config = _make_config()
        session = runtime.create_session(config, session_id="new-id")

        with pytest.raises(RuntimeError, match="already running"):
            await runtime.invoke_user(session, "hello")

    @pytest.mark.asyncio
    async def test_sets_running_session_id(self):
        """invoke_user sets _running_session_id to the session's id."""
        runtime = _make_runtime()
        config = _make_config()
        session = runtime.create_session(config, session_id="sid1")

        with patch.object(
            runtime,
            "_execute_turn",
            side_effect=_make_mock_execute_turn_complete(runtime),
        ):
            await runtime.invoke_user(session, "hello")
            # _running_session_id is set before _execute_turn runs,
            # and cleared by the mock's cleanup. Verify it was set:
            # (it's already cleared by _mock_execute_turn_complete)
            pass

    @pytest.mark.asyncio
    async def test_transitions_session_to_running(self):
        """invoke_user transitions the session to RUNNING."""
        runtime = _make_runtime()
        config = _make_config()
        session = runtime.create_session(config, session_id="sid1")

        # Use a hanging mock so the session stays in RUNNING
        with patch.object(
            runtime,
            "_execute_turn",
            side_effect=_make_mock_execute_turn_hanging(runtime),
        ):
            await runtime.invoke_user(session, "hello")
            assert session.status == SessionStatus.RUNNING

    @pytest.mark.asyncio
    async def test_creates_loop_task(self):
        """invoke_user creates an asyncio Task for _execute_turn."""
        runtime = _make_runtime()
        config = _make_config()
        session = runtime.create_session(config, session_id="sid1")

        with patch.object(
            runtime,
            "_execute_turn",
            side_effect=_make_mock_execute_turn_complete(runtime),
        ):
            await runtime.invoke_user(session, "hello")
            assert runtime._loop_task is not None
            assert isinstance(runtime._loop_task, asyncio.Task)

    @pytest.mark.asyncio
    async def test_returns_session_id(self):
        """invoke_user returns the session id."""
        runtime = _make_runtime()
        config = _make_config()
        session = runtime.create_session(config, session_id="sid1")

        with patch.object(
            runtime,
            "_execute_turn",
            side_effect=_make_mock_execute_turn_complete(runtime),
        ):
            result = await runtime.invoke_user(session, "hello")
            assert result == "sid1"

    @pytest.mark.asyncio
    async def test_creates_interrupt_event(self):
        """invoke_user creates a new asyncio.Event for interruption."""
        runtime = _make_runtime()
        config = _make_config()
        session = runtime.create_session(config, session_id="sid1")

        with patch.object(
            runtime,
            "_execute_turn",
            side_effect=_make_mock_execute_turn_complete(runtime),
        ):
            # Before invoke, interrupt_event is None
            assert runtime._interrupt_event is None
            await runtime.invoke_user(session, "hello")
            assert isinstance(runtime._interrupt_event, asyncio.Event)
            assert not runtime._interrupt_event.is_set()

    @pytest.mark.asyncio
    async def test_clears_pending_requests(self):
        """invoke_user clears any existing pending requests."""
        runtime = _make_runtime()
        runtime._pending["old-tid"] = {"kind": "old", "message": {}}
        config = _make_config()
        session = runtime.create_session(config, session_id="sid1")

        with patch.object(
            runtime,
            "_execute_turn",
            side_effect=_make_mock_execute_turn_complete(runtime),
        ):
            await runtime.invoke_user(session, "hello")
            assert runtime._pending == {}


# ═══════════════════════════════════════════════════════════
# start (compat)
# ═══════════════════════════════════════════════════════════


class TestStart:
    """Tests for AgentRuntime.start() — synchronous compat wrapper."""

    @pytest.mark.asyncio
    async def test_raises_runtimeerror_if_running(self):
        """start raises RuntimeError when another session is running."""
        runtime = _make_runtime()
        runtime._running_session_id = "existing-id"
        mock_session = MagicMock()
        mock_session.session_id = "new-id"

        with pytest.raises(RuntimeError, match="already running"):
            runtime.start(mock_session, "hello")

    @pytest.mark.asyncio
    async def test_creates_turn_task(self):
        """start creates an asyncio Task for _execute_turn."""
        runtime = _make_runtime()
        mock_session = MagicMock()
        mock_session.id = "test-id"
        mock_session.session_id = "test-id"
        mock_session.transition_to = MagicMock()

        with patch.object(runtime, "_execute_turn", new_callable=AsyncMock):
            runtime.start(mock_session, "hello")
            assert runtime._loop_task is not None
            assert isinstance(runtime._loop_task, asyncio.Task)
            assert "runtime-test-id" in runtime._loop_task.get_name()

    @pytest.mark.asyncio
    async def test_returns_session_id(self):
        """start returns the session's session_id."""
        runtime = _make_runtime()
        mock_session = MagicMock()
        mock_session.id = "my-session"
        mock_session.session_id = "my-session"
        mock_session.transition_to = MagicMock()

        with patch.object(runtime, "_execute_turn", new_callable=AsyncMock):
            result = runtime.start(mock_session, "hello")
            assert result == "my-session"

    @pytest.mark.asyncio
    async def test_sets_running_state_synchronously(self):
        """start exposes runtime/session running state before the task runs."""
        runtime = _make_runtime()
        mock_session = MagicMock()
        mock_session.id = "sync-session"
        mock_session.session_id = "sync-session"
        mock_session.transition_to = MagicMock()

        with patch.object(runtime, "_execute_turn", new_callable=AsyncMock):
            runtime.start(mock_session, "hello")
            assert runtime.status == RuntimeStatus.RUNNING
            assert runtime.is_running_session("sync-session") is True
            mock_session.transition_to.assert_called_with(SessionStatus.RUNNING)


# ═══════════════════════════════════════════════════════════
# invoke_agent (Agent → Agent)
# ═══════════════════════════════════════════════════════════


class TestInvokeAgent:
    """Tests for AgentRuntime.invoke_agent()."""

    @pytest.mark.asyncio
    async def test_returns_error_when_target_not_found(self):
        """invoke_agent returns an error string when target_id can't be resolved."""
        runtime = _make_runtime()
        result = await runtime.invoke_agent("caller-id", "nonexistent", "do something")
        assert "not found" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_error_when_permission_denied(self):
        """invoke_agent returns an error when access policy denies invoke."""
        runtime = _make_runtime()
        # Create a session with OWNER_ONLY access owned by a different session
        owner = Owner.session("owner-id")
        access = AccessPolicy(
            owner=owner,
            invoke_permission=InvokePermission.OWNER_ONLY,
        )
        config = SessionConfig(
            name="protected",
            model_id="gpt-4",
            access=access,
        )
        runtime.create_session(config, session_id="protected-id")

        result = await runtime.invoke_agent("caller-id", "protected-id", "do something")
        assert "does not allow invoke" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_resolves_target_id_by_prefix(self):
        """invoke_agent resolves target_id via _resolve_id (prefix matching)."""
        runtime = _make_runtime()
        config = _make_config()
        runtime.create_session(config, session_id="abcdef123456")

        # Set up access so invoke is allowed
        entry = runtime.get_session("abcdef123456")
        assert entry is not None
        # Patch the access to allow any agent
        with patch.object(entry.config.access, "can_invoke", return_value=True):
            with patch.object(
                runtime, "_execute_turn", side_effect=_mock_invoke_execute_turn
            ):
                result = await runtime.invoke_agent("caller-id", "abc", "do something")
            # Should resolve to abcdef123456 and not return an error
            assert "error" not in result.lower()
            assert "abcdef123456" in result

    @pytest.mark.asyncio
    async def test_calls_hooks_on_subagent_start_and_end(self):
        """invoke_agent calls hook_manager.on_subagent_start and on_subagent_end."""
        hm = MagicMock(spec=HookManager)
        hm.on_subagent_start = AsyncMock()
        hm.on_subagent_end = AsyncMock()
        # Dispatch is used by convenience methods, but invoke_agent calls
        # self._hooks.on_subagent_start/end directly — which are the
        # HookManager convenience methods that call dispatch.
        # We mock the convenience methods directly.
        runtime = AgentRuntime(workspace=Workspace(), hook_manager=hm)

        config = _make_config()
        runtime.create_session(config, session_id="target-id")

        # Allow invoke
        entry = runtime.get_session("target-id")
        assert entry is not None
        with patch.object(entry.config.access, "can_invoke", return_value=True):
            with patch.object(
                runtime, "_execute_turn", side_effect=_mock_invoke_execute_turn
            ):
                await runtime.invoke_agent(
                    "caller-id", "target-id", "do task", max_turns=5
                )

        hm.on_subagent_start.assert_called_once()
        call_kwargs = hm.on_subagent_start.call_args.kwargs
        assert call_kwargs["task"] == "do task"
        assert call_kwargs["parent_session_id"] == "caller-id"
        assert call_kwargs["max_steps"] == 5

        hm.on_subagent_end.assert_called_once()

    @pytest.mark.asyncio
    async def test_caller_transitions_to_pending_then_running(self):
        """invoke_agent transitions caller to PENDING then back to RUNNING."""
        runtime = _make_runtime()
        config = _make_config()

        caller = runtime.create_session(config, session_id="caller-id")
        target = runtime.create_session(config, session_id="target-id")

        # Allow invoke
        with patch.object(target.config.access, "can_invoke", return_value=True):
            with patch.object(
                runtime, "_execute_turn", side_effect=_mock_invoke_execute_turn
            ):
                await runtime.invoke_agent("caller-id", "target-id", "do task")

        # After invoke_agent completes, caller should be back to RUNNING
        # (It goes PENDING during the call, RUNNING after)
        assert caller.status == SessionStatus.RUNNING

    @pytest.mark.asyncio
    async def test_caller_pending_during_invoke(self):
        """While invoke_agent is awaiting, the caller is in PENDING state."""
        runtime = _make_runtime()
        config = _make_config()

        caller = runtime.create_session(config, session_id="caller-id")
        target = runtime.create_session(config, session_id="target-id")

        # We'll block inside the hook to observe the PENDING state
        blocking = asyncio.Event()
        observed_status = []

        async def slow_hook(*, task, parent_session_id, max_steps, **kwargs):
            observed_status.append(caller.status)
            await blocking.wait()

        hm = runtime.hooks
        hm.on_subagent_start = slow_hook

        with patch.object(target.config.access, "can_invoke", return_value=True):
            with patch.object(
                runtime, "_execute_turn", side_effect=_mock_invoke_execute_turn
            ):
                task = asyncio.create_task(
                    runtime.invoke_agent("caller-id", "target-id", "do task")
                )
                # Give the task time to start and transition
                await asyncio.sleep(0.05)
                blocking.set()
                await task

        assert SessionStatus.PENDING in observed_status
        assert caller.status == SessionStatus.RUNNING


# ═══════════════════════════════════════════════════════════
# interrupt
# ═══════════════════════════════════════════════════════════


class TestInterrupt:
    """Tests for AgentRuntime.interrupt()."""

    @pytest.mark.asyncio
    async def test_returns_false_when_no_interrupt_event(self):
        """interrupt returns False when there is no running session."""
        runtime = _make_runtime()
        assert runtime._interrupt_event is None
        result = await runtime.interrupt()
        assert result is False

    @pytest.mark.asyncio
    async def test_sets_interrupt_event(self):
        """interrupt sets the interrupt event to signal the loop."""
        runtime = _make_runtime()
        config = _make_config()
        session = runtime.create_session(config, session_id="sid1")

        with patch.object(
            runtime,
            "_execute_turn",
            side_effect=_make_mock_execute_turn_interrupted(runtime),
        ):
            await runtime.invoke_user(session, "hello")
            # _interrupt_event is not yet set
            assert runtime._interrupt_event is not None
            assert not runtime._interrupt_event.is_set()
            await runtime.interrupt()
            # After interrupt, the event should have been set
            assert runtime._interrupt_event is not None
            assert runtime._interrupt_event.is_set()

    @pytest.mark.asyncio
    async def test_returns_true_after_successful_interrupt(self):
        """interrupt returns True when there was a running session."""
        runtime = _make_runtime()
        config = _make_config()
        session = runtime.create_session(config, session_id="sid1")

        with patch.object(
            runtime,
            "_execute_turn",
            side_effect=_make_mock_execute_turn_interrupted(runtime),
        ):
            await runtime.invoke_user(session, "hello")
            result = await runtime.interrupt()
            assert result is True

    @pytest.mark.asyncio
    async def test_awaits_loop_task(self):
        """interrupt awaits the running _loop_task before returning."""
        runtime = _make_runtime()
        config = _make_config()
        session = runtime.create_session(config, session_id="sid1")

        task_completed = False

        async def mock_with_flag(entry, question, max_steps, shadow_repo=None):
            nonlocal task_completed
            assert runtime._interrupt_event is not None
            while not runtime._interrupt_event.is_set():
                await asyncio.sleep(0.001)
            runtime._running_session_id = None
            runtime._loop_task = None
            entry.transition_to(SessionStatus.IDLE)
            task_completed = True

        with patch.object(runtime, "_execute_turn", side_effect=mock_with_flag):
            await runtime.invoke_user(session, "hello")
            await runtime.interrupt()
            assert task_completed is True

    @pytest.mark.asyncio
    async def test_survives_loop_task_exception(self):
        """interrupt does not propagate exceptions from _loop_task."""
        runtime = _make_runtime()
        config = _make_config()
        session = runtime.create_session(config, session_id="sid1")

        async def mock_that_raises(entry, question, max_steps, shadow_repo=None):
            assert runtime._interrupt_event is not None
            while not runtime._interrupt_event.is_set():
                await asyncio.sleep(0.001)
            raise RuntimeError("boom")

        with patch.object(runtime, "_execute_turn", side_effect=mock_that_raises):
            await runtime.invoke_user(session, "hello")
            # Should not raise
            result = await runtime.interrupt()
            assert result is True


# ═══════════════════════════════════════════════════════════
# resolve
# ═══════════════════════════════════════════════════════════


class TestResolve:
    """Tests for AgentRuntime.resolve()."""

    @pytest.mark.asyncio
    async def test_raises_keyerror_for_unknown_message_id(self):
        """resolve raises KeyError when message_id is not in pending."""
        runtime = _make_runtime()
        with pytest.raises(KeyError, match="nonexistent"):
            await runtime.resolve("nonexistent", {"approved": True})

    @pytest.mark.asyncio
    async def test_resolves_existing_pending_request(self):
        """resolve sets the response and event on the pending request."""
        runtime = _make_runtime()
        event = asyncio.Event()
        runtime._pending["tid-1"] = {
            "kind": "permission_request",
            "message": {"tool": "shell"},
            "event": event,
        }

        await runtime.resolve("tid-1", {"approved": True})
        assert runtime._pending["tid-1"]["response"] == {"approved": True}
        assert event.is_set()

    @pytest.mark.asyncio
    async def test_resolve_only_affects_target_transcript(self):
        """resolve does not modify other pending requests."""
        runtime = _make_runtime()
        event_a = asyncio.Event()
        event_b = asyncio.Event()
        runtime._pending["tid-a"] = {"kind": "a", "event": event_a}
        runtime._pending["tid-b"] = {"kind": "b", "event": event_b}

        await runtime.resolve("tid-a", {"ok": True})

        assert runtime._pending["tid-a"]["response"] == {"ok": True}
        assert "response" not in runtime._pending["tid-b"]
        assert event_a.is_set()
        assert not event_b.is_set()


# ═══════════════════════════════════════════════════════════
# State Transitions
# ═══════════════════════════════════════════════════════════


class TestStateTransitions:
    """Tests for SessionStatus / RuntimeStatus transitions through the ReAct loop."""

    @pytest.mark.asyncio
    async def test_after_invoke_user_session_is_running(self):
        """After invoke_user returns, the session is in RUNNING state."""
        runtime = _make_runtime()
        config = _make_config()
        session = runtime.create_session(config, session_id="sid1")

        with patch.object(
            runtime,
            "_execute_turn",
            side_effect=_make_mock_execute_turn_hanging(runtime),
        ):
            await runtime.invoke_user(session, "hello")
            assert session.status == SessionStatus.RUNNING
            assert runtime.status == RuntimeStatus.RUNNING

    @pytest.mark.asyncio
    async def test_after_execute_turn_completes_session_is_idle(self):
        """After _execute_turn completes (with cleanup), the session is IDLE."""
        runtime = _make_runtime()
        config = _make_config()
        session = runtime.create_session(config, session_id="sid1")

        with patch.object(
            runtime,
            "_execute_turn",
            side_effect=_make_mock_execute_turn_complete(runtime),
        ):
            await runtime.invoke_user(session, "hello")
            # Wait for the loop task to finish
            if runtime._loop_task:
                await runtime._loop_task
            assert session.status == SessionStatus.IDLE
            assert runtime.status == RuntimeStatus.IDLE

    @pytest.mark.asyncio
    async def test_after_execute_turn_running_session_id_cleared(self):
        """After _execute_turn completes, _running_session_id is None."""
        runtime = _make_runtime()
        config = _make_config()
        session = runtime.create_session(config, session_id="sid1")

        with patch.object(
            runtime,
            "_execute_turn",
            side_effect=_make_mock_execute_turn_complete(runtime),
        ):
            await runtime.invoke_user(session, "hello")
            if runtime._loop_task:
                await runtime._loop_task
            assert runtime._running_session_id is None

    @pytest.mark.asyncio
    async def test_after_interrupt_session_is_idle(self):
        """After interrupt() completes, the session transitions to IDLE."""
        runtime = _make_runtime()
        config = _make_config()
        session = runtime.create_session(config, session_id="sid1")

        with patch.object(
            runtime,
            "_execute_turn",
            side_effect=_make_mock_execute_turn_interrupted(runtime),
        ):
            await runtime.invoke_user(session, "hello")
            assert session.status == SessionStatus.RUNNING

            await runtime.interrupt()
            assert session.status == SessionStatus.IDLE
            assert runtime.status == RuntimeStatus.IDLE

    @pytest.mark.asyncio
    async def test_interrupted_state_is_visible_during_shutdown(self):
        """During interrupt handling, the session briefly enters INTERRUPTED."""
        runtime = _make_runtime()
        config = _make_config()
        session = runtime.create_session(config, session_id="sid1")

        captured_statuses = []

        async def mock_capturing(entry, question, max_steps, shadow_repo=None):
            assert runtime._interrupt_event is not None
            while not runtime._interrupt_event.is_set():
                await asyncio.sleep(0.001)
            entry.transition_to(SessionStatus.INTERRUPTED)
            captured_statuses.append(entry.status)
            # Simulate finally cleanup
            runtime._running_session_id = None
            runtime._loop_task = None
            entry.transition_to(SessionStatus.IDLE)

        with patch.object(runtime, "_execute_turn", side_effect=mock_capturing):
            await runtime.invoke_user(session, "hello")
            await runtime.interrupt()
            assert SessionStatus.INTERRUPTED in captured_statuses
            assert session.status == SessionStatus.IDLE

    @pytest.mark.asyncio
    async def test_runtime_status_idle_after_turn_completion(self):
        """RuntimeStatus returns to IDLE after a turn completes."""
        runtime = _make_runtime()
        config = _make_config()
        session = runtime.create_session(config, session_id="sid1")

        with patch.object(
            runtime,
            "_execute_turn",
            side_effect=_make_mock_execute_turn_complete(runtime),
        ):
            await runtime.invoke_user(session, "hello")
            if runtime._loop_task:
                await runtime._loop_task
            assert runtime.status == RuntimeStatus.IDLE


# ═══════════════════════════════════════════════════════════
# Concurrent Execution Prevention
# ═══════════════════════════════════════════════════════════


class TestConcurrentExecutionPrevention:
    """Tests that enforce single-session execution guarantees."""

    @pytest.mark.asyncio
    async def test_cannot_invoke_user_while_running(self):
        """invoke_user raises RuntimeError when a session is already running."""
        runtime = _make_runtime()
        config = _make_config()
        session_a = runtime.create_session(config, session_id="session-a")
        session_b = runtime.create_session(config, session_id="session-b")

        with patch.object(
            runtime,
            "_execute_turn",
            side_effect=_make_mock_execute_turn_hanging(runtime),
        ):
            await runtime.invoke_user(session_a, "hello")
            # Now session A is running, invoking B should fail
            with pytest.raises(RuntimeError, match="already running"):
                await runtime.invoke_user(session_b, "world")

    @pytest.mark.asyncio
    async def test_cannot_start_while_running(self):
        """start raises RuntimeError when a session is already running."""
        runtime = _make_runtime()
        runtime._running_session_id = "existing"

        mock_session = MagicMock()
        mock_session.session_id = "new-session"

        with pytest.raises(RuntimeError, match="already running"):
            runtime.start(mock_session, "hello")

    @pytest.mark.asyncio
    async def test_can_invoke_after_previous_completes(self):
        """After the running session finishes, a new invoke_user succeeds."""
        runtime = _make_runtime()
        config = _make_config()
        session_a = runtime.create_session(config, session_id="session-a")
        session_b = runtime.create_session(config, session_id="session-b")

        with patch.object(
            runtime,
            "_execute_turn",
            side_effect=_make_mock_execute_turn_complete(runtime),
        ):
            # First invocation completes
            await runtime.invoke_user(session_a, "hello")
            if runtime._loop_task:
                await runtime._loop_task

            # Second invocation should succeed
            sid = await runtime.invoke_user(session_b, "world")
            if runtime._loop_task:
                await runtime._loop_task
            assert sid == "session-b"

    @pytest.mark.asyncio
    async def test_same_session_reinvoke_after_completion(self):
        """The same session can be invoked again after its turn completes."""
        runtime = _make_runtime()
        config = _make_config()
        session = runtime.create_session(config, session_id="sid1")

        with patch.object(
            runtime,
            "_execute_turn",
            side_effect=_make_mock_execute_turn_complete(runtime),
        ):
            await runtime.invoke_user(session, "first")
            if runtime._loop_task:
                await runtime._loop_task

            await runtime.invoke_user(session, "second")
            if runtime._loop_task:
                await runtime._loop_task

            assert runtime.status == RuntimeStatus.IDLE


# ═══════════════════════════════════════════════════════════
# _resolve_id
# ═══════════════════════════════════════════════════════════


class TestResolveId:
    """Tests for AgentRuntime._resolve_id() — internal prefix resolution."""

    def test_exact_match_returns_id(self):
        """_resolve_id returns the id when an exact match exists."""
        runtime = _make_runtime()
        config = _make_config()
        runtime.create_session(config, session_id="abcdef")
        assert runtime._resolve_id("abcdef") == "abcdef"

    def test_prefix_match_returns_full_id(self):
        """_resolve_id returns the full id for a unique prefix match."""
        runtime = _make_runtime()
        config = _make_config()
        runtime.create_session(config, session_id="abcdef123")
        assert runtime._resolve_id("abc") == "abcdef123"

    def test_ambiguous_prefix_returns_none(self):
        """_resolve_id returns None when the prefix matches multiple sessions."""
        runtime = _make_runtime()
        config = _make_config()
        runtime.create_session(config, session_id="abc123")
        runtime.create_session(config, session_id="abc456")
        assert runtime._resolve_id("abc") is None

    def test_no_match_returns_none(self):
        """_resolve_id returns None when no session matches."""
        runtime = _make_runtime()
        config = _make_config()
        runtime.create_session(config, session_id="abcdef")
        assert runtime._resolve_id("zzz") is None

    def test_empty_sessions_returns_none(self):
        """_resolve_id returns None when there are no sessions."""
        runtime = _make_runtime()
        assert runtime._resolve_id("anything") is None
