"""Comprehensive unit tests for the Session + Workspace chain (链路 5).

Covers:
- agent/core/workspace.py   — Workspace
- agent/core/config.py      — SessionConfig, AgentConfig, AccessPolicy, ToolSetPreset
- agent/session/status.py   — SessionStatus, RuntimeStatus
- agent/session/entry.py    — SessionEntry
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from agent.core.config import (
    AccessPolicy,
    AgentConfig,
    InvokePermission,
    Lifecycle,
    Owner,
    SessionConfig,
    ToolSetPreset,
    Visibility,
)
from agent.core.workspace import BYTE_AGENT_DIR, Workspace
from agent.core.workspace import Workspace as Workspace
from agent.session.entry import SessionEntry
from agent.session.status import RuntimeStatus, SessionStatus

# ═══════════════════════════════════════════════════════════════════
# Workspace tests
# ═══════════════════════════════════════════════════════════════════


class TestWorkspaceConstructor:
    """Tests for Workspace.__init__()."""

    def test_default_root_is_cwd(self):
        """When root is None, workspace root defaults to Path.cwd()."""
        ws = Workspace()
        assert ws.root == Path.cwd()

    def test_explicit_root_string(self):
        """Constructor accepts a string path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            assert ws.root == Path(tmpdir).resolve()

    def test_explicit_root_path(self):
        """Constructor accepts a Path object."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=Path(tmpdir))
            assert ws.root == Path(tmpdir).resolve()

    def test_root_expands_user_tilde(self):
        """The root path expands ~ to the user home directory."""
        ws = Workspace(root=Path("~/test_workspace"))
        assert str(ws.root).startswith(str(Path.home()))

    def test_repr(self):
        """repr() shows the workspace root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            assert repr(ws) == f"Workspace({Path(tmpdir).resolve()})"


class TestWorkspaceDirectoryPaths:
    """Tests for directory path generation methods."""

    def test_agent_dir(self):
        """agent_dir() returns root/.byte_agent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            assert ws.agent_dir() == Path(tmpdir).resolve() / BYTE_AGENT_DIR

    def test_sessions_dir(self):
        """sessions_dir() returns root/.byte_agent/sessions/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            assert (
                ws.sessions_dir()
                == Path(tmpdir).resolve() / BYTE_AGENT_DIR / "sessions"
            )

    def test_session_dir(self):
        """session_dir(sid) returns root/.byte_agent/sessions/{sid}/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            assert ws.session_dir("abc123") == (
                Path(tmpdir).resolve() / BYTE_AGENT_DIR / "sessions" / "abc123"
            )


class TestWorkspaceFilePaths:
    """Tests for file path generation methods."""

    def test_session_db_path(self):
        """session_db_path returns session_dir/session.db."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            expected = ws.session_dir("abc123") / "session.db"
            assert ws.session_db_path("abc123") == expected

    def test_session_config_path(self):
        """session_config_path returns session_dir/config.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            expected = ws.session_dir("abc123") / "config.json"
            assert ws.session_config_path("abc123") == expected

    def test_tasks_path(self):
        """tasks_path returns session_dir/tasks.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            expected = ws.session_dir("abc123") / "tasks.json"
            assert ws.tasks_path("abc123") == expected

    def test_messages_path(self):
        """messages_path returns session_dir/messages.jsonl."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            expected = ws.session_dir("abc123") / "messages.jsonl"
            assert ws.messages_path("abc123") == expected


class TestValidateSessionId:
    """Tests for Workspace._validate_session_id()."""

    def test_accepts_lowercase_and_digits(self):
        """Valid session IDs contain only lowercase letters and digits."""
        # These should not raise
        Workspace._validate_session_id("abc123")
        Workspace._validate_session_id("session1")
        Workspace._validate_session_id("test001")
        Workspace._validate_session_id("a")
        Workspace._validate_session_id("0")

    def test_rejects_uppercase(self):
        """Session IDs with uppercase letters are rejected."""
        with pytest.raises(ValueError, match="Invalid session_id"):
            Workspace._validate_session_id("ABC")
        with pytest.raises(ValueError, match="Invalid session_id"):
            Workspace._validate_session_id("Abc123")
        with pytest.raises(ValueError, match="Invalid session_id"):
            Workspace._validate_session_id("UPPERCASE")

    def test_rejects_special_characters(self):
        """Session IDs with special characters are rejected (hyphens now allowed)."""
        with pytest.raises(ValueError, match="Invalid session_id"):
            Workspace._validate_session_id("abc_123")
        with pytest.raises(ValueError, match="Invalid session_id"):
            Workspace._validate_session_id("abc 123")
        with pytest.raises(ValueError, match="Invalid session_id"):
            Workspace._validate_session_id("abc.123")
        with pytest.raises(ValueError, match="Invalid session_id"):
            Workspace._validate_session_id("/etc")

    def test_allows_hyphens(self):
        """Session IDs may contain hyphens."""
        Workspace._validate_session_id("abc-123")
        Workspace._validate_session_id("my-custom-id")
        Workspace._validate_session_id("a-b-c")

    def test_rejects_empty_string(self):
        """Empty string is rejected."""
        with pytest.raises(ValueError, match="Invalid session_id"):
            Workspace._validate_session_id("")


class TestWorkspaceEnsureDirs:
    """Tests for Workspace.ensure_dirs()."""

    def test_creates_session_directory(self):
        """ensure_dirs creates the session directory and returns its path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            sid = "testsession"
            # Directory should not exist before
            assert not ws.session_dir(sid).exists()
            result = ws.ensure_dirs(sid)
            # Directory should exist after
            assert result.exists()
            assert result.is_dir()
            assert result == ws.session_dir(sid)

    def test_create_parent_directories(self):
        """ensure_dirs creates all parent directories as needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            sid = "nested"
            # Neither sessions_dir nor session_dir exist
            assert not ws.sessions_dir().exists()
            ws.ensure_dirs(sid)
            assert ws.sessions_dir().exists()
            assert ws.session_dir(sid).exists()


class TestWorkspaceSaveLoadConfig:
    """Tests for save_session_config / load_session_config round-trip."""

    def test_round_trip(self):
        """save_session_config then load_session_config returns equivalent data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            sid = "configtest"
            config = SessionConfig(
                name="test-session",
                model_id="gpt-4",
                preamble="You are a helpful assistant.",
                tool_set_preset=ToolSetPreset.CODE_ONLY,
                custom_tools=["my_tool"],
                preloaded_skills=["skill_a"],
                rules=["rule1", "rule2"],
                access=AccessPolicy.user_default(),
            )
            ws.save_session_config(sid, config)

            # Verify file exists
            assert ws.session_config_path(sid).exists()

            loaded = ws.load_session_config(sid)
            assert loaded is not None
            assert loaded["name"] == "test-session"
            assert loaded["model_id"] == "gpt-4"
            assert loaded["preamble"] == "You are a helpful assistant."
            assert loaded["tool_set_preset"] == "code_only"
            assert loaded["custom_tools"] == ["my_tool"]
            assert loaded["preloaded_skills"] == ["skill_a"]
            assert loaded["rules"] == ["rule1", "rule2"]
            # Access policy fields
            access = loaded["access"]
            assert access["owner"]["kind"] == "user"
            assert access["visibility"] == "private"
            assert access["invoke_permission"] == "owner_only"
            assert access["lifecycle"] == "persistent"

    def test_load_nonexistent_config(self):
        """load_session_config returns None for a session with no config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            assert ws.load_session_config("nonexistent") is None

    def test_config_file_created_by_save(self):
        """save_session_config writes a valid JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            sid = "saveonly"
            config = SessionConfig(
                name="minimal",
                model_id="claude-3",
            )
            ws.save_session_config(sid, config)
            path = ws.session_config_path(sid)
            # Verify it is valid JSON
            raw = path.read_text()
            data = json.loads(raw)
            assert data["name"] == "minimal"
            assert data["model_id"] == "claude-3"


class TestWorkspaceListSessionIds:
    """Tests for Workspace.list_session_ids()."""

    def test_empty_when_no_sessions(self):
        """Returns empty list when no session directories exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            assert ws.list_session_ids() == []

    def test_no_sessions_dir_yet(self):
        """Returns empty list when sessions dir doesn't even exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            # Don't create sessions dir
            assert ws.list_session_ids() == []

    def test_lists_created_sessions(self):
        """Returns sorted session IDs from created directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            ws.ensure_dirs("session2")
            ws.ensure_dirs("session1")
            ws.ensure_dirs("session10")
            ids = ws.list_session_ids()
            # Sorted alphabetically
            assert ids == ["session1", "session10", "session2"]

    def test_filters_non_directories(self):
        """Only directories matching session ID pattern are returned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            ws.ensure_dirs("valid1")
            # Create a file in sessions_dir (not a directory)
            ws.sessions_dir().mkdir(parents=True, exist_ok=True)
            (ws.sessions_dir() / "not_a_session.txt").write_text("nope")
            ids = ws.list_session_ids()
            assert ids == ["valid1"]

    def test_filters_invalid_names(self):
        """Directories with invalid session ID names are excluded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            ws.ensure_dirs("good")
            # Manually create directories with invalid names
            (ws.sessions_dir() / "BAD_SESSION").mkdir(parents=True, exist_ok=True)
            (ws.sessions_dir() / "with.dots").mkdir(parents=True, exist_ok=True)
            (ws.sessions_dir() / "has spaces").mkdir(parents=True, exist_ok=True)
            ids = ws.list_session_ids()
            assert ids == ["good"]


class TestWorkspaceResolve:
    """Tests for Workspace.resolve() — path traversal prevention."""

    def test_resolve_normal_path(self):
        """Normal relative paths resolve within the workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            result = ws.resolve("some/file.txt")
            assert result == (Path(tmpdir).resolve() / "some" / "file.txt")

    def test_resolve_dotdot_raises_permission_error(self):
        """Resolving '..' raises PermissionError (path traversal)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            with pytest.raises(PermissionError, match="Path traversal denied"):
                ws.resolve("..")

    def test_resolve_deep_dotdot_raises_permission_error(self):
        """Resolving deeply nested '..' raises PermissionError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            with pytest.raises(PermissionError, match="Path traversal denied"):
                ws.resolve("subdir/../../etc")

    def test_resolve_absolute_path_raises_permission_error(self):
        """Resolving an absolute path outside workspace raises PermissionError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            with pytest.raises(PermissionError, match="Path traversal denied"):
                ws.resolve("/etc/passwd")

    def test_resolve_empty_string(self):
        """Resolving empty string gives workspace root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            result = ws.resolve("")
            assert result == Path(tmpdir).resolve()


class TestWorkspaceIsSafePath:
    """Tests for Workspace.is_safe_path()."""

    def test_safe_relative_path(self):
        """An absolute path within workspace is safe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            (Path(tmpdir) / "subdir").mkdir()
            filepath = str(Path(tmpdir) / "subdir" / "file.txt")
            Path(filepath).write_text("")
            assert ws.is_safe_path(filepath) is True

    def test_safe_absolute_path_inside(self):
        """An absolute path inside workspace is safe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            inside = str(Path(tmpdir) / "some" / "file.txt")
            assert ws.is_safe_path(inside) is True

    def test_unsafe_path_outside(self):
        """A path outside workspace is not safe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            assert ws.is_safe_path("/etc/passwd") is False

    def test_unsafe_dotdot(self):
        """A path with '..' escaping workspace is not safe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            outside = str(Path(tmpdir) / ".." / "other")
            assert ws.is_safe_path(outside) is False

    def test_safe_path_object(self):
        """is_safe_path accepts Path objects."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)
            assert ws.is_safe_path(Path(tmpdir) / "sub") is True


# ═══════════════════════════════════════════════════════════════════
# SessionConfig tests
# ═══════════════════════════════════════════════════════════════════


class TestSessionConfigUserMain:
    """Tests for SessionConfig.user_main() factory."""

    def test_creates_with_all_toolset(self):
        """user_main() defaults to ALL toolset preset."""
        config = SessionConfig.user_main(
            name="main",
            model_id="gpt-4",
        )
        assert config.tool_set_preset == ToolSetPreset.ALL
        assert config.model_id == "gpt-4"
        assert config.name == "main"

    def test_creates_with_user_default_access(self):
        """user_main() uses AccessPolicy.user_default()."""
        config = SessionConfig.user_main(
            name="main",
            model_id="gpt-4",
        )
        assert config.access == AccessPolicy.user_default()
        assert config.access.owner.kind == "user"
        assert config.access.visibility == Visibility.PRIVATE
        assert config.access.invoke_permission == InvokePermission.OWNER_ONLY
        assert config.access.lifecycle == Lifecycle.PERSISTENT

    def test_optional_preamble(self):
        """user_main() accepts an optional preamble."""
        config = SessionConfig.user_main(
            name="main",
            model_id="gpt-4",
            preamble="Be concise.",
        )
        assert config.preamble == "Be concise."

    def test_default_preamble_is_empty(self):
        """When preamble is not provided, it defaults to empty string."""
        config = SessionConfig.user_main(
            name="main",
            model_id="gpt-4",
        )
        assert config.preamble == ""


class TestSessionConfigSubagent:
    """Tests for SessionConfig.subagent() factory."""

    def test_has_whitelist_invoke_permission(self):
        """subagent() creates config with WHITELIST invoke_permission."""
        config = SessionConfig.subagent(
            parent_id="parent123",
            name="sub",
            task="Do something",
            model_id="gpt-4",
        )
        assert config.access.invoke_permission == InvokePermission.WHITELIST

    def test_whitelist_contains_parent_id(self):
        """subagent() whitelist contains the parent session ID."""
        config = SessionConfig.subagent(
            parent_id="parent123",
            name="sub",
            task="Do something",
            model_id="gpt-4",
        )
        assert "parent123" in config.access.whitelist_ids

    def test_owner_is_parent_session(self):
        """subagent() owner is the parent session."""
        config = SessionConfig.subagent(
            parent_id="parent123",
            name="sub",
            task="Do something",
            model_id="gpt-4",
        )
        assert config.access.owner.kind == "session"
        assert config.access.owner.session_id == "parent123"

    def test_task_becomes_rule(self):
        """subagent() stores the task as a rule."""
        config = SessionConfig.subagent(
            parent_id="parent123",
            name="sub",
            task="Summarize the document.",
            model_id="gpt-4",
        )
        assert "Summarize the document." in config.rules

    def test_lifecycle_is_ephemeral(self):
        """subagent() defaults to EPHEMERAL lifecycle."""
        config = SessionConfig.subagent(
            parent_id="parent123",
            name="sub",
            task="Do something",
            model_id="gpt-4",
        )
        assert config.access.lifecycle == Lifecycle.EPHEMERAL

    def test_visibility_is_private(self):
        """subagent() defaults to PRIVATE visibility."""
        config = SessionConfig.subagent(
            parent_id="parent123",
            name="sub",
            task="Do something",
            model_id="gpt-4",
        )
        assert config.access.visibility == Visibility.PRIVATE

    def test_custom_toolset_preset(self):
        """subagent() accepts an optional tool_set_preset."""
        config = SessionConfig.subagent(
            parent_id="parent123",
            name="sub",
            task="Do something",
            model_id="gpt-4",
            tool_set_preset=ToolSetPreset.MINIMAL,
        )
        assert config.tool_set_preset == ToolSetPreset.MINIMAL


class TestSessionConfigToolNames:
    """Tests for SessionConfig.tool_names()."""

    def test_all_preset_returns_preset_tools(self):
        """When preset is ALL, tool_names() returns the ALL preset list."""
        config = SessionConfig(tool_set_preset=ToolSetPreset.ALL)
        assert config.tool_names() == ToolSetPreset.ALL.tool_names()

    def test_custom_overrides_preset(self):
        """When preset is CUSTOM and custom_tools is set, returns custom_tools."""
        config = SessionConfig(
            tool_set_preset=ToolSetPreset.CUSTOM,
            custom_tools=["ToolA", "ToolB"],
        )
        assert config.tool_names() == ["ToolA", "ToolB"]

    def test_custom_empty_by_default(self):
        """When preset is CUSTOM but custom_tools is empty, returns empty list."""
        config = SessionConfig(tool_set_preset=ToolSetPreset.CUSTOM)
        assert config.tool_names() == []

    def test_code_only_preset(self):
        """CODE_ONLY preset returns correct tool list."""
        config = SessionConfig(tool_set_preset=ToolSetPreset.CODE_ONLY)
        expected = ToolSetPreset.CODE_ONLY.tool_names()
        assert config.tool_names() == expected
        assert "Shell" in expected
        assert "Edit" in expected

    def test_review_only_preset(self):
        """REVIEW_ONLY preset returns read-only tools."""
        config = SessionConfig(tool_set_preset=ToolSetPreset.REVIEW_ONLY)
        expected = ToolSetPreset.REVIEW_ONLY.tool_names()
        # Should not include write/edit/shell
        assert "Write" not in expected
        assert "Edit" not in expected
        assert "Shell" not in expected
        assert "Read" in expected


class TestSessionConfigFrozen:
    """Tests that SessionConfig is a frozen (immutable) dataclass."""

    def test_cannot_set_attributes(self):
        """Setting an attribute on a SessionConfig instance raises FrozenInstanceError."""
        config = SessionConfig(name="test")
        with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
            config.name = "changed"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════
# AgentConfig tests
# ═══════════════════════════════════════════════════════════════════


class TestAgentConfig:
    """Tests for AgentConfig."""

    def test_default_values(self):
        """Default AgentConfig has sensible defaults."""
        config = AgentConfig()
        assert config.model_id == ""
        assert config.temperature == 0.0
        assert config.max_tokens is None

    def test_with_model_returns_new_instance(self):
        """with_model() returns a new AgentConfig with updated model_id."""
        original = AgentConfig(model_id="gpt-3", temperature=0.5, max_tokens=100)
        updated = original.with_model("gpt-4")
        # New instance
        assert updated is not original
        assert updated.model_id == "gpt-4"
        # Other fields preserved
        assert updated.temperature == 0.5
        assert updated.max_tokens == 100
        # Original unchanged
        assert original.model_id == "gpt-3"

    def test_with_model_does_not_mutate_original(self):
        """with_model() does not mutate the original AgentConfig."""
        original = AgentConfig(model_id="original-model")
        _updated = original.with_model("new-model")
        assert original.model_id == "original-model"

    def test_frozen_dataclass(self):
        """AgentConfig is a frozen dataclass."""
        config = AgentConfig(model_id="test")
        with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
            config.model_id = "altered"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════
# AccessPolicy tests
# ═══════════════════════════════════════════════════════════════════


class TestAccessPolicyUserDefault:
    """Tests for AccessPolicy.user_default()."""

    def test_owner_is_user(self):
        """Default owner is a user (not a session)."""
        policy = AccessPolicy.user_default()
        assert policy.owner == Owner.user()
        assert policy.owner.kind == "user"
        assert policy.owner.session_id is None

    def test_visibility_is_private(self):
        """Default visibility is PRIVATE."""
        policy = AccessPolicy.user_default()
        assert policy.visibility == Visibility.PRIVATE

    def test_invoke_permission_is_owner_only(self):
        """Default invoke_permission is OWNER_ONLY."""
        policy = AccessPolicy.user_default()
        assert policy.invoke_permission == InvokePermission.OWNER_ONLY

    def test_lifecycle_is_persistent(self):
        """Default lifecycle is PERSISTENT."""
        policy = AccessPolicy.user_default()
        assert policy.lifecycle == Lifecycle.PERSISTENT


class TestAccessPolicySubagent:
    """Tests for AccessPolicy.subagent(parent_id)."""

    def test_owner_is_session(self):
        """Subagent owner is a session (the parent)."""
        policy = AccessPolicy.subagent("parent_001")
        assert policy.owner.kind == "session"
        assert policy.owner.session_id == "parent_001"

    def test_whitelist_contains_parent_id(self):
        """Subagent whitelist only contains the parent ID."""
        policy = AccessPolicy.subagent("parent_001")
        assert policy.whitelist_ids == ["parent_001"]

    def test_invoke_permission_is_whitelist(self):
        """Subagent invoke_permission is WHITELIST."""
        policy = AccessPolicy.subagent("parent_001")
        assert policy.invoke_permission == InvokePermission.WHITELIST

    def test_lifecycle_is_ephemeral(self):
        """Subagent lifecycle is EPHEMERAL."""
        policy = AccessPolicy.subagent("parent_001")
        assert policy.lifecycle == Lifecycle.EPHEMERAL

    def test_visibility_is_private(self):
        """Subagent visibility is PRIVATE."""
        policy = AccessPolicy.subagent("parent_001")
        assert policy.visibility == Visibility.PRIVATE


class TestAccessPolicyCanInvoke:
    """Tests for AccessPolicy.can_invoke()."""

    # ── OWNER_ONLY ──────────────────────────────────────

    def test_owner_only_user_owner_user_caller(self):
        """When owner is user and invoke is OWNER_ONLY, user (None) can invoke."""
        policy = AccessPolicy(
            owner=Owner.user(),
            invoke_permission=InvokePermission.OWNER_ONLY,
        )
        assert policy.can_invoke(None) is True

    def test_owner_only_user_owner_session_caller(self):
        """When owner is user and invoke is OWNER_ONLY, a session cannot invoke."""
        policy = AccessPolicy(
            owner=Owner.user(),
            invoke_permission=InvokePermission.OWNER_ONLY,
        )
        assert policy.can_invoke("other_session") is False

    def test_owner_only_session_owner_matching_caller(self):
        """When owner is session and invoke is OWNER_ONLY, only that session can invoke."""
        policy = AccessPolicy(
            owner=Owner.session("session_x"),
            invoke_permission=InvokePermission.OWNER_ONLY,
        )
        assert policy.can_invoke("session_x") is True

    def test_owner_only_session_owner_non_matching_caller(self):
        """When owner is session and invoke is OWNER_ONLY, other sessions cannot invoke."""
        policy = AccessPolicy(
            owner=Owner.session("session_x"),
            invoke_permission=InvokePermission.OWNER_ONLY,
        )
        assert policy.can_invoke("session_y") is False

    # ── WHITELIST ───────────────────────────────────────

    def test_whitelist_allows_listed_caller(self):
        """A caller in the whitelist can invoke."""
        policy = AccessPolicy(
            invoke_permission=InvokePermission.WHITELIST,
            whitelist_ids=["allowed_001", "allowed_002"],
        )
        assert policy.can_invoke("allowed_001") is True

    def test_whitelist_denies_unlisted_caller(self):
        """A caller not in the whitelist cannot invoke."""
        policy = AccessPolicy(
            invoke_permission=InvokePermission.WHITELIST,
            whitelist_ids=["allowed_001"],
        )
        assert policy.can_invoke("intruder") is False

    def test_whitelist_denies_none_caller(self):
        """None (user) cannot invoke a whitelist-only session."""
        policy = AccessPolicy(
            invoke_permission=InvokePermission.WHITELIST,
            whitelist_ids=["allowed_001"],
        )
        assert policy.can_invoke(None) is False

    # ── ANY_AGENT ───────────────────────────────────────

    def test_any_agent_allows_session_caller(self):
        """ANY_AGENT allows any session to invoke."""
        policy = AccessPolicy(
            invoke_permission=InvokePermission.ANY_AGENT,
        )
        assert policy.can_invoke("any_session") is True

    def test_any_agent_allows_none_caller(self):
        """ANY_AGENT allows user (None) to invoke."""
        policy = AccessPolicy(
            invoke_permission=InvokePermission.ANY_AGENT,
        )
        assert policy.can_invoke(None) is True


class TestAccessPolicyIsVisibleTo:
    """Tests for AccessPolicy.is_visible_to()."""

    # ── PRIVATE ─────────────────────────────────────────

    def test_private_user_owner_visible_to_user(self):
        """PRIVATE with user owner: visible to user (None)."""
        policy = AccessPolicy(
            owner=Owner.user(),
            visibility=Visibility.PRIVATE,
        )
        assert policy.is_visible_to(None) is True

    def test_private_user_owner_not_visible_to_session(self):
        """PRIVATE with user owner: not visible to other sessions."""
        policy = AccessPolicy(
            owner=Owner.user(),
            visibility=Visibility.PRIVATE,
        )
        assert policy.is_visible_to("other_session") is False

    def test_private_session_owner_visible_to_owner(self):
        """PRIVATE with session owner: visible to the owning session."""
        policy = AccessPolicy(
            owner=Owner.session("session_x"),
            visibility=Visibility.PRIVATE,
        )
        assert policy.is_visible_to("session_x") is True

    def test_private_session_owner_not_visible_to_other(self):
        """PRIVATE with session owner: not visible to other sessions."""
        policy = AccessPolicy(
            owner=Owner.session("session_x"),
            visibility=Visibility.PRIVATE,
        )
        assert policy.is_visible_to("session_y") is False

    # ── WHITELIST ───────────────────────────────────────

    def test_whitelist_visible_to_listed(self):
        """WHITELIST visibility: listed seekers can see it."""
        policy = AccessPolicy(
            visibility=Visibility.WHITELIST,
            whitelist_ids=["friend_001"],
        )
        assert policy.is_visible_to("friend_001") is True

    def test_whitelist_not_visible_to_unlisted(self):
        """WHITELIST visibility: unlisted seekers cannot see it."""
        policy = AccessPolicy(
            visibility=Visibility.WHITELIST,
            whitelist_ids=["friend_001"],
        )
        assert policy.is_visible_to("stranger") is False

    def test_whitelist_not_visible_to_none(self):
        """WHITELIST visibility: None (user) cannot see it."""
        policy = AccessPolicy(
            visibility=Visibility.WHITELIST,
            whitelist_ids=["friend_001"],
        )
        assert policy.is_visible_to(None) is False

    # ── PUBLIC ──────────────────────────────────────────

    def test_public_visible_to_session(self):
        """PUBLIC visibility: any session can see it."""
        policy = AccessPolicy(visibility=Visibility.PUBLIC)
        assert policy.is_visible_to("any_session") is True

    def test_public_visible_to_user(self):
        """PUBLIC visibility: user (None) can see it."""
        policy = AccessPolicy(visibility=Visibility.PUBLIC)
        assert policy.is_visible_to(None) is True

    def test_public_visible_to_anyone(self):
        """PUBLIC visibility: visible regardless of seeker."""
        policy = AccessPolicy(visibility=Visibility.PUBLIC)
        assert policy.is_visible_to("literally_anything") is True


# ═══════════════════════════════════════════════════════════════════
# Owner tests
# ═══════════════════════════════════════════════════════════════════


class TestOwner:
    """Tests for the Owner class."""

    def test_user_factory(self):
        """Owner.user() creates a user owner with kind='user'."""
        owner = Owner.user()
        assert owner.kind == "user"
        assert owner.session_id is None

    def test_session_factory(self):
        """Owner.session(sid) creates a session owner."""
        owner = Owner.session("abc123")
        assert owner.kind == "session"
        assert owner.session_id == "abc123"

    def test_equality(self):
        """Owner supports equality comparison."""
        assert Owner.user() == Owner.user()
        assert Owner.session("x") == Owner.session("x")
        assert Owner.user() != Owner.session("x")
        assert Owner.session("x") != Owner.session("y")

    def test_hash(self):
        """Owner is hashable (can be used in sets/dicts)."""
        owners = {Owner.user(), Owner.session("x")}
        assert Owner.user() in owners
        assert Owner.session("x") in owners
        assert Owner.session("y") not in owners


# ═══════════════════════════════════════════════════════════════════
# ToolSetPreset tests
# ═══════════════════════════════════════════════════════════════════


class TestToolSetPreset:
    """Tests for ToolSetPreset enum."""

    def test_all_values_exist(self):
        """All expected enum values are defined."""
        assert ToolSetPreset.ALL.value == "all"
        assert ToolSetPreset.MINIMAL.value == "minimal"
        assert ToolSetPreset.CODE_ONLY.value == "code_only"
        assert ToolSetPreset.REVIEW_ONLY.value == "review_only"
        assert ToolSetPreset.CUSTOM.value == "custom"

    def test_all_tool_names_is_comprehensive(self):
        """ALL preset includes the widest set of tools."""
        names = ToolSetPreset.ALL.tool_names()
        assert "WebSearch" in names
        assert "Shell" in names
        assert "Read" in names
        assert "Write" in names
        assert "Edit" in names
        assert "SubAgent" in names

    def test_minimal_is_restricted(self):
        """MINIMAL preset includes only basic tools."""
        names = ToolSetPreset.MINIMAL.tool_names()
        assert len(names) == 5
        assert "ListDir" in names
        assert "Read" in names
        assert "Write" in names
        assert "Glob" in names
        assert "Grep" in names
        assert "Shell" not in names
        assert "Edit" not in names

    def test_custom_returns_empty(self):
        """CUSTOM preset returns empty list from tool_names()."""
        names = ToolSetPreset.CUSTOM.tool_names()
        assert names == []


# ═══════════════════════════════════════════════════════════════════
# SessionStatus tests
# ═══════════════════════════════════════════════════════════════════


class TestSessionStatus:
    """Tests for SessionStatus enum."""

    def test_all_enum_values(self):
        """All four SessionStatus values are defined."""
        assert SessionStatus.IDLE.value == "idle"
        assert SessionStatus.RUNNING.value == "running"
        assert SessionStatus.PENDING.value == "pending"
        assert SessionStatus.INTERRUPTED.value == "interrupted"

    def test_idle_is_invokable(self):
        """Only IDLE is invokable."""
        assert SessionStatus.IDLE.is_invokable() is True

    def test_running_not_invokable(self):
        """RUNNING is not invokable."""
        assert SessionStatus.RUNNING.is_invokable() is False

    def test_pending_not_invokable(self):
        """PENDING is not invokable."""
        assert SessionStatus.PENDING.is_invokable() is False

    def test_interrupted_not_invokable(self):
        """INTERRUPTED is not invokable."""
        # INTERRUPTED is also not IDLE, so it should NOT be invokable
        assert SessionStatus.INTERRUPTED.is_invokable() is False

    def test_running_is_busy(self):
        """RUNNING is busy."""
        assert SessionStatus.RUNNING.is_busy() is True

    def test_pending_is_busy(self):
        """PENDING is busy."""
        assert SessionStatus.PENDING.is_busy() is True

    def test_idle_not_busy(self):
        """IDLE is not busy."""
        assert SessionStatus.IDLE.is_busy() is False

    def test_interrupted_not_busy(self):
        """INTERRUPTED is not busy."""
        assert SessionStatus.INTERRUPTED.is_busy() is False

    def test_string_enum_can_compare_with_strings(self):
        """SessionStatus is a str enum, comparable to plain strings."""
        assert SessionStatus.IDLE == "idle"
        assert SessionStatus.RUNNING == "running"


# ═══════════════════════════════════════════════════════════════════
# RuntimeStatus tests
# ═══════════════════════════════════════════════════════════════════


class TestRuntimeStatus:
    """Tests for RuntimeStatus enum."""

    def test_values(self):
        """RuntimeStatus has IDLE and RUNNING values."""
        assert RuntimeStatus.IDLE.value == "idle"
        assert RuntimeStatus.RUNNING.value == "running"

    def test_string_enum(self):
        """RuntimeStatus is a str enum."""
        assert RuntimeStatus.IDLE == "idle"
        assert RuntimeStatus.RUNNING == "running"


# ═══════════════════════════════════════════════════════════════════
# SessionEntry tests
# ═══════════════════════════════════════════════════════════════════


class TestSessionEntryDefaults:
    """Tests for SessionEntry default values."""

    def test_default_status_is_idle(self):
        """A new SessionEntry has IDLE status by default."""
        config = SessionConfig.user_main(name="test", model_id="gpt-4")
        entry = SessionEntry(id="session_001", config=config)
        assert entry.status == SessionStatus.IDLE

    def test_default_ws_is_created(self):
        """SessionEntry creates a default Workspace."""
        config = SessionConfig.user_main(name="test", model_id="gpt-4")
        entry = SessionEntry(id="session_001", config=config)
        assert isinstance(entry.ws, Workspace)

    def test_default_llm_client_is_none(self):
        """SessionEntry default llm_client is None."""
        config = SessionConfig.user_main(name="test", model_id="gpt-4")
        entry = SessionEntry(id="session_001", config=config)
        assert entry.llm_client is None

    def test_session_id_property(self):
        """id field serves as the session identifier."""
        config = SessionConfig.user_main(name="test", model_id="gpt-4")
        entry = SessionEntry(id="abc", config=config)
        assert entry.id == "abc"

    def test_model_id_property(self):
        """model_id property delegates to config.model_id."""
        config = SessionConfig.user_main(name="test", model_id="claude-3")
        entry = SessionEntry(id="abc", config=config)
        assert entry.model_id == "claude-3"


class TestSessionEntryProperties:
    """Tests for SessionEntry is_idle / is_busy properties."""

    def test_is_idle_when_idle(self):
        """is_idle is True when status is IDLE."""
        config = SessionConfig.user_main(name="test", model_id="gpt-4")
        entry = SessionEntry(id="s1", config=config)
        entry.status = SessionStatus.IDLE
        assert entry.is_idle is True
        assert entry.is_busy is False

    def test_is_idle_when_running(self):
        """is_idle is False when status is RUNNING."""
        config = SessionConfig.user_main(name="test", model_id="gpt-4")
        entry = SessionEntry(id="s1", config=config)
        entry.status = SessionStatus.RUNNING
        assert entry.is_idle is False
        assert entry.is_busy is True

    def test_is_busy_when_pending(self):
        """is_busy is True when status is PENDING."""
        config = SessionConfig.user_main(name="test", model_id="gpt-4")
        entry = SessionEntry(id="s1", config=config)
        entry.status = SessionStatus.PENDING
        assert entry.is_busy is True
        assert entry.is_idle is False

    def test_is_busy_when_interrupted(self):
        """INTERRUPTED is neither idle nor busy."""
        config = SessionConfig.user_main(name="test", model_id="gpt-4")
        entry = SessionEntry(id="s1", config=config)
        entry.status = SessionStatus.INTERRUPTED
        assert entry.is_idle is False
        assert entry.is_busy is False


class TestSessionEntryTransition:
    """Tests for SessionEntry.transition_to()."""

    def test_transition_idle_to_running(self):
        """transition_to changes status from IDLE to RUNNING."""
        config = SessionConfig.user_main(name="test", model_id="gpt-4")
        entry = SessionEntry(id="s1", config=config)
        assert entry.status == SessionStatus.IDLE
        entry.transition_to(SessionStatus.RUNNING)
        assert entry.status == SessionStatus.RUNNING

    def test_transition_running_to_idle(self):
        """transition_to changes status from RUNNING back to IDLE."""
        config = SessionConfig.user_main(name="test", model_id="gpt-4")
        entry = SessionEntry(id="s1", config=config)
        entry.transition_to(SessionStatus.RUNNING)
        entry.transition_to(SessionStatus.IDLE)
        assert entry.status == SessionStatus.IDLE

    def test_transition_running_to_pending(self):
        """transition_to can change from RUNNING to PENDING."""
        config = SessionConfig.user_main(name="test", model_id="gpt-4")
        entry = SessionEntry(id="s1", config=config)
        entry.transition_to(SessionStatus.RUNNING)
        entry.transition_to(SessionStatus.PENDING)
        assert entry.status == SessionStatus.PENDING

    def test_transition_to_interrupted(self):
        """transition_to can change to INTERRUPTED."""
        config = SessionConfig.user_main(name="test", model_id="gpt-4")
        entry = SessionEntry(id="s1", config=config)
        entry.transition_to(SessionStatus.RUNNING)
        entry.transition_to(SessionStatus.INTERRUPTED)
        assert entry.status == SessionStatus.INTERRUPTED


# ═══════════════════════════════════════════════════════════════════
# Integrated chain tests
# ═══════════════════════════════════════════════════════════════════


class TestSessionWorkspaceChain:
    """End-to-end chain tests tying Workspace + SessionConfig + SessionEntry together."""

    def test_full_chain_user_session(self):
        """Simulate creating a user main session end-to-end."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Create workspace
            ws = Workspace(root=tmpdir)

            # 2. Create session config
            config = SessionConfig.user_main(
                name="My Session",
                model_id="gpt-4",
                preamble="Be helpful.",
            )

            # 3. Create session entry
            entry = SessionEntry(id="mysession", config=config)

            # 4. Verify entry state
            assert entry.id == "mysession"
            assert entry.is_idle
            assert entry.config.tool_set_preset == ToolSetPreset.ALL
            assert entry.config.access.invoke_permission == InvokePermission.OWNER_ONLY

            # 5. Persist config via workspace
            ws.save_session_config("mysession", config)
            assert ws.session_config_path("mysession").exists()

            # 6. Load back and verify
            loaded = ws.load_session_config("mysession")
            assert loaded is not None
            assert loaded["name"] == "My Session"

            # 7. Verify session appears in listed IDs
            assert "mysession" in ws.list_session_ids()

    def test_full_chain_subagent(self):
        """Simulate creating a subagent session end-to-end."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(root=tmpdir)

            # Create parent main session
            parent_config = SessionConfig.user_main(
                name="Parent",
                model_id="gpt-4",
            )
            parent_entry = SessionEntry(id="parent001", config=parent_config)
            ws.save_session_config("parent001", parent_config)

            # Create subagent from parent
            sub_config = SessionConfig.subagent(
                parent_id="parent001",
                name="Sub-worker",
                task="Analyze the logs.",
                model_id="gpt-4",
                tool_set_preset=ToolSetPreset.MINIMAL,
            )
            sub_entry = SessionEntry(id="sub001", config=sub_config)
            ws.save_session_config("sub001", sub_config)

            # Verify access control
            assert sub_config.access.owner.kind == "session"
            assert sub_config.access.owner.session_id == "parent001"
            assert sub_config.access.invoke_permission == InvokePermission.WHITELIST
            assert sub_config.access.can_invoke("parent001") is True
            assert sub_config.access.can_invoke("other") is False

            # Verify both sessions are listed
            ids = ws.list_session_ids()
            assert "parent001" in ids
            assert "sub001" in ids

    def test_status_lifecycle(self):
        """Test the full status lifecycle: IDLE -> RUNNING -> PENDING -> IDLE."""
        config = SessionConfig.user_main(name="lifecycle", model_id="gpt-4")
        entry = SessionEntry(id="lifecycle_session", config=config)

        # Start idle
        assert entry.is_idle
        assert not entry.is_busy
        assert entry.status.is_invokable()

        # Transition to running
        entry.transition_to(SessionStatus.RUNNING)
        assert entry.is_busy
        assert not entry.is_idle
        assert not entry.status.is_invokable()

        # Transition to pending (waiting for sub-agent)
        entry.transition_to(SessionStatus.PENDING)
        assert entry.is_busy
        assert not entry.status.is_invokable()

        # Back to running
        entry.transition_to(SessionStatus.RUNNING)
        assert entry.is_busy

        # Back to idle
        entry.transition_to(SessionStatus.IDLE)
        assert entry.is_idle
        assert not entry.is_busy
        assert entry.status.is_invokable()
