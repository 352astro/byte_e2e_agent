"""Unit tests for Workspace (Sandbox) — path management and I/O.

Covers:
- agent/core/workspace.py — Workspace (and Sandbox alias)
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

import pytest

from agent.core.workspace import Workspace


@pytest.fixture
def tmp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def ws(tmp_workspace):
    return Workspace(root=tmp_workspace, workspace_uuid="test-workspace")


class TestWorkspaceConstruction:
    def test_root_stored_as_absolute_path(self, ws):
        assert ws.root.is_absolute()

    def test_requires_workspace_uuid(self, tmp_workspace):
        with pytest.raises(TypeError):
            Workspace(root=tmp_workspace)

    def test_root_with_path_object(self, tmp_workspace):
        p = Path(tmp_workspace)
        w = Workspace(root=p, workspace_uuid="test-workspace")
        assert w.root == p.resolve()

    def test_creates_directory_if_missing(self):
        with tempfile.TemporaryDirectory() as td:
            new_dir = Path(td) / "new_workspace"
            w = Workspace(root=new_dir, workspace_uuid="test-workspace")
            assert new_dir.exists()


class TestWorkspacePathManagement:
    def test_resolve_relative_path(self, ws):
        resolved = ws.resolve("subdir/file.py")
        assert resolved.is_absolute()
        assert str(ws.root) in str(resolved)

    def test_resolve_path_returns_string(self, ws):
        result = ws.resolve_path(".")
        assert isinstance(result, str)
        assert result == str(ws.root)

    def test_resolve_raises_on_escape_attempt(self, ws):
        with pytest.raises(PermissionError):
            ws.resolve("../../../etc/passwd")

    def test_resolve_path_raises_on_escape(self, ws):
        with pytest.raises(PermissionError):
            ws.resolve_path("../../../etc/passwd")

    def test_is_safe_path_true(self, ws):
        assert ws.is_safe_path(ws.root / "file.py") is True

    def test_is_safe_path_false(self, ws):
        assert ws.is_safe_path("/etc/passwd") is False

    def test_agent_dir(self, ws):
        d = ws.agent_dir()
        assert d.name == ws.uuid
        assert d.parent.name == "workspaces"

    def test_sessions_dir(self, ws):
        d = ws.sessions_dir()
        assert d.parent == ws.agent_dir()

    def test_session_dir(self, ws):
        d = ws.session_dir("abc123")
        assert d.name == "abc123"

    def test_invalid_session_id_raises(self, ws):
        with pytest.raises(ValueError):
            ws.session_dir("INVALID-ID")


class TestWorkspaceShell:
    @pytest.mark.asyncio
    async def test_run_shell_echo(self, ws):
        result = await ws.run_shell("echo hello")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_run_shell_in_workspace_dir(self, ws):
        result = await ws.run_shell("pwd")
        assert str(ws.root) in result

    @pytest.mark.asyncio
    async def test_run_shell_exit_code_nonzero(self, ws):
        result = await ws.run_shell("exit 1")
        assert "exit code: 1" in result

    @pytest.mark.asyncio
    async def test_run_shell_timeout(self, ws):
        result = await ws.run_shell("sleep 5", timeout_ms=100)
        assert "timed out" in result.lower()

    @pytest.mark.asyncio
    async def test_run_shell_interrupt_kills_process(self, ws):
        interrupt_event = asyncio.Event()

        async def trigger_interrupt():
            await asyncio.sleep(0.1)
            interrupt_event.set()

        start = time.perf_counter()
        trigger_task = asyncio.create_task(trigger_interrupt())
        result = await ws.run_shell(
            "sleep 5", timeout_ms=5000, interrupt_event=interrupt_event
        )
        await trigger_task

        assert "interrupted" in result.lower()
        assert time.perf_counter() - start < 1.5


class TestWorkspaceFileIO:
    @pytest.mark.asyncio
    async def test_read_file(self, ws):
        (ws.root / "test.txt").write_text("hello world")
        result = await ws.read_file("test.txt")
        assert "hello world" in result

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, ws):
        result = await ws.read_file("nonexistent.txt")
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_write_file(self, ws):
        result = await ws.write_file("new.txt", "content")
        assert "Successfully" in result
        assert (ws.root / "new.txt").read_text() == "content"

    @pytest.mark.asyncio
    async def test_write_file_creates_parent_dirs(self, ws):
        result = await ws.write_file("sub/deep/file.txt", "data")
        assert "Successfully" in result
        assert (ws.root / "sub" / "deep" / "file.txt").exists()

    @pytest.mark.asyncio
    async def test_write_file_path_escape_blocked(self, ws):
        result = await ws.write_file("../../../escape.txt", "bad")
        assert "Error" in result


class TestWorkspaceRepr:
    def test_repr(self, ws):
        r = repr(ws)
        assert "Workspace" in r
        assert str(ws.root) in r
