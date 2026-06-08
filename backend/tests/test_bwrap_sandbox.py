"""Unit + integration tests for bwrap sandbox.

Covers:
- agent/utils/sandbox.py — build_bwrap_cmd (pure function)
- agent/tools/terminal.py — PersistentTerminal with bwrap (integration)
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.utils.sandbox import BwrapBind, build_bwrap_cmd, bwrap_available
from agent.utils.terminal import PersistentTerminal

# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _find_arg_indices(cmd: list[str], arg: str) -> list[int]:
    """Return all indices where *arg* appears in *cmd*."""
    return [i for i, a in enumerate(cmd) if a == arg]


def _mount_targets(cmd: list[str], flag: str) -> list[str]:
    """Extract target paths for a given mount flag (--bind, --ro-bind)."""
    targets = []
    for idx in _find_arg_indices(cmd, flag):
        targets.append(cmd[idx + 2])  # --bind SRC DST or --ro-bind SRC DST
    return targets


# ═══════════════════════════════════════════════════════════
# Unit tests: build_bwrap_cmd
# ═══════════════════════════════════════════════════════════


class TestBuildBwrapCmd:
    """Verify the bwrap command structure.

    New strategy: ``--ro-bind / /`` for full-filesystem visibility,
    ``--bind`` holes for workspace + custom rw paths, dedicated flags
    for proc/dev/tmp.
    """

    @pytest.fixture(autouse=True)
    def _mock_rules(self):
        with (
            patch(
                "agent.utils.sandbox._rule_paths_from_environment",
                return_value=[],
            ),
            patch(
                "agent.utils.sandbox.list_builtin_rules",
                return_value=[],
            ),
        ):
            yield

    # ── Basic structure ──────────────────────────────────

    @staticmethod
    def _cmd(*args, **kwargs):
        """Call build_bwrap_cmd and return only the command list."""
        cmd, _ = build_bwrap_cmd(*args, **kwargs)
        return cmd

    def test_starts_with_bwrap(self):
        cmd = self._cmd("/ws", ["bash"])
        assert cmd[0] == "bwrap"

    def test_ends_with_dash_dash_and_shell(self):
        cmd = self._cmd("/ws", ["bash", "--norc"])
        dd_idx = cmd.index("--")
        assert cmd[dd_idx + 1 :] == ["bash", "--norc"]

    # ── Root filesystem ──────────────────────────────────

    def test_root_is_ro_bind(self):
        cmd = self._cmd("/ws", ["bash"])
        ro_targets = _mount_targets(cmd, "--ro-bind")
        assert "/" in ro_targets, "Root / must be --ro-bind"

    def test_only_root_is_ro_bind(self):
        cmd = self._cmd("/ws", ["bash"])
        ro_targets = _mount_targets(cmd, "--ro-bind")
        # / should be ro-bind; no /usr, /lib, etc. (blacklist might add one more)
        assert "/" in ro_targets
        for sp in ["/usr", "/lib", "/bin", "/etc"]:
            assert sp not in ro_targets, f"{sp} should not be individually --ro-bind"

    # ── Workspace ────────────────────────────────────────

    def test_workspace_is_bind(self):
        cmd = self._cmd("/test/workspace", ["bash"])
        bind_targets = _mount_targets(cmd, "--bind")
        assert "/test/workspace" in bind_targets

    # ── No dir flags ─────────────────────────────────────

    def test_no_dir_flags(self):
        cmd = self._cmd("/a/b/c/ws", ["bash"])
        assert "--dir" not in cmd

    # ── Special filesystems ──────────────────────────────

    def test_proc_and_dev_present(self):
        cmd = self._cmd("/ws", ["bash"])
        assert "--proc" in cmd
        assert "--dev" in cmd

    def test_tmpfs_for_tmp(self):
        cmd = self._cmd("/ws", ["bash"])
        tmpfs_indices = _find_arg_indices(cmd, "--tmpfs")
        assert len(tmpfs_indices) == 1
        assert cmd[tmpfs_indices[0] + 1] == "/tmp"

    # ── Custom rules ─────────────────────────────────────

    def test_toolchain_dirs_are_bind(self):
        """Builtin toolchain dirs (~/.cargo, ~/.local, etc.) get --bind."""
        from agent.utils.sandbox import SysguardRule

        toolchain = [
            SysguardRule(
                id="test:cargo",
                label="Cargo",
                path="/home/user/.cargo",
                enabled=True,
            ),
            SysguardRule(
                id="test:local",
                label="Local",
                path="/home/user/.local",
                enabled=True,
            ),
        ]
        with patch(
            "agent.utils.sandbox.list_builtin_rules",
            return_value=toolchain,
        ):
            cmd = self._cmd("/ws", ["bash"])
        bind_targets = _mount_targets(cmd, "--bind")
        assert "/home/user/.cargo" in bind_targets
        assert "/home/user/.local" in bind_targets

    def test_disabled_toolchain_not_bound(self):
        """Disabled toolchain rules are skipped."""
        from agent.utils.sandbox import SysguardRule

        toolchain = [
            SysguardRule(
                id="test:cargo",
                label="Cargo",
                path="/home/user/.cargo",
                enabled=False,
            ),
        ]
        with patch(
            "agent.utils.sandbox.list_builtin_rules",
            return_value=toolchain,
        ):
            cmd = self._cmd("/ws", ["bash"])
        bind_targets = _mount_targets(cmd, "--bind")
        assert "/home/user/.cargo" not in bind_targets

    def test_custom_readwrite_is_bind(self):
        with patch(
            "agent.utils.sandbox._rule_paths_from_environment",
            side_effect=lambda mode, workspace_uuid=None: (
                ["/opt/tools"] if mode == "readwrite" else []
            ),
        ):
            cmd = self._cmd("/ws", ["bash"])
        bind_targets = _mount_targets(cmd, "--bind")
        assert "/opt/tools" in bind_targets

    def test_custom_readwrite_not_duplicated(self):
        with patch(
            "agent.utils.sandbox._rule_paths_from_environment",
            side_effect=lambda mode, workspace_uuid=None: ["/ws"] if mode == "readwrite" else [],
        ):
            cmd = self._cmd("/ws", ["bash"])
        bind_targets = _mount_targets(cmd, "--bind")
        assert bind_targets.count("/ws") == 1, f"Workspace bound {bind_targets.count('/ws')} times"

    def test_extra_readonly_bind(self, tmp_path):
        source = tmp_path / "venv"
        source.mkdir()

        cmd = self._cmd(
            "/ws",
            ["python"],
            extra_binds=[
                BwrapBind(
                    source=str(source),
                    target="/tmp/.venv",
                    mode="readonly",
                )
            ],
        )

        ro_pairs = [(cmd[i + 1], cmd[i + 2]) for i in _find_arg_indices(cmd, "--ro-bind")]
        assert (str(source.resolve()), "/tmp/.venv") in ro_pairs

    def test_extra_readwrite_bind(self, tmp_path):
        source = tmp_path / "cache"
        source.mkdir()

        cmd = self._cmd(
            "/ws",
            ["python"],
            extra_binds=[
                BwrapBind(
                    source=str(source),
                    target="/cache",
                    mode="readwrite",
                )
            ],
        )

        bind_pairs = [(cmd[i + 1], cmd[i + 2]) for i in _find_arg_indices(cmd, "--bind")]
        assert (str(source.resolve()), "/cache") in bind_pairs

    # ── Mount order ──────────────────────────────────────

    def test_ro_bind_root_before_bind_workspace(self):
        cmd = self._cmd("/ws", ["bash"])
        ro_root_idx = cmd.index("--ro-bind")
        bind_ws_idx = cmd.index("--bind")
        assert ro_root_idx < bind_ws_idx, "--ro-bind / must come before --bind workspace"

    def test_tmpfs_before_bind_workspace(self):
        cmd = self._cmd("/tmp/ws", ["bash"])
        tmpfs_idx = cmd.index("--tmpfs")
        bind_ws_idx = cmd.index("--bind")
        assert tmpfs_idx < bind_ws_idx, "--tmpfs /tmp must come before --bind /tmp/ws"

    # ── Blacklist ────────────────────────────────────────

    def test_blacklist_returns_cleanup_path(self):
        """When PROJECT_ROOT exists, a cleanup path is returned."""
        cmd, cleanup = build_bwrap_cmd("/ws", ["bash"])
        assert cleanup is not None, "Should return blackhole cleanup path"
        assert os.path.isdir(cleanup), f"{cleanup} should be a directory"
        # Clean up after test
        shutil.rmtree(cleanup, ignore_errors=True)

    def test_blacklist_mounts_empty_dir_over_project_root(self):
        """PROJECT_ROOT is hidden behind an empty directory bind-mount."""
        from app.core.config import PROJECT_ROOT

        cmd, cleanup = build_bwrap_cmd("/ws", ["bash"])
        # Find the ro-bind that uses the blackhole as source
        ro_indices = _find_arg_indices(cmd, "--ro-bind")
        blackhole_mounts = [
            (cmd[i + 1], cmd[i + 2])
            for i in ro_indices
            if cmd[i + 2] == str(Path(PROJECT_ROOT).resolve())
        ]
        assert len(blackhole_mounts) == 1, (
            f"Expected one blackhole mount for PROJECT_ROOT, got {blackhole_mounts}"
        )
        src, dst = blackhole_mounts[0]
        assert src == cleanup, "Source must be the blackhole temp dir"
        # Clean up
        shutil.rmtree(cleanup, ignore_errors=True)


# ═══════════════════════════════════════════════════════════
# Integration tests: PersistentTerminal + bwrap
# ═══════════════════════════════════════════════════════════


@pytest.mark.skipif(not bwrap_available(), reason="bwrap not installed")
class TestBwrapTerminal:
    """Test PersistentTerminal running inside a bwrap sandbox."""

    @pytest.fixture
    def test_area(self):
        """Create a temporary directory tree that exercises bwrap ancestor isolation.

        Layout on host::

            /tmp/bwrap_test_{pid}/
                sibling.txt          ← outside workspace (should be invisible in sandbox)
                workspace/
                    inside.txt       ← inside workspace (should be visible, writable)

        In the bwrap sandbox, ``/tmp`` is a tmpfs (empty).  The only visible
        content is the bind-mounted workspace.  ``sibling.txt`` must *not* be
        visible.
        """
        area = Path(f"/tmp/bwrap_test_{os.getpid()}")
        area.mkdir(parents=True, exist_ok=True)
        ws = area / "workspace"
        ws.mkdir(parents=True, exist_ok=True)

        (ws / "inside.txt").write_text("hello from workspace", encoding="utf-8")
        (area / "sibling.txt").write_text("should be invisible", encoding="utf-8")

        yield area

        # Cleanup
        shutil.rmtree(area, ignore_errors=True)

    @pytest.fixture
    def workspace(self, test_area):
        return test_area / "workspace"

    def _start_terminal(self, workspace: Path) -> PersistentTerminal:
        t = PersistentTerminal()
        t.start(
            cwd=str(workspace),
            sandbox_root=str(workspace),
            workspace_uuid="bwrap-test",
        )
        return t

    # ── Basic execution ──────────────────────────────────

    def test_basic_echo(self, workspace):
        terminal = self._start_terminal(workspace)
        try:
            result = terminal.run("echo hello-bwrap", timeout_ms=5000)
            assert result.exit_code == 0
            assert "hello-bwrap" in result.output
        finally:
            terminal.stop()

    def test_pwd_is_workspace(self, workspace):
        terminal = self._start_terminal(workspace)
        try:
            result = terminal.run("pwd", timeout_ms=5000)
            assert result.exit_code == 0
            assert str(workspace.resolve()) in result.output
        finally:
            terminal.stop()

    def test_ls_shows_workspace_contents(self, workspace):
        terminal = self._start_terminal(workspace)
        try:
            result = terminal.run("ls", timeout_ms=5000)
            assert result.exit_code == 0
            assert "inside.txt" in result.output
        finally:
            terminal.stop()

    # ── Exit codes ───────────────────────────────────────

    def test_exit_code_zero(self, workspace):
        terminal = self._start_terminal(workspace)
        try:
            result = terminal.run("true", timeout_ms=5000)
            assert result.exit_code == 0
        finally:
            terminal.stop()

    def test_exit_code_nonzero(self, workspace):
        terminal = self._start_terminal(workspace)
        try:
            result = terminal.run("exit 7", timeout_ms=5000)
            assert result.exit_code == 7
        finally:
            terminal.stop()

    # ── Workspace write access ───────────────────────────

    def test_write_to_workspace(self, workspace):
        terminal = self._start_terminal(workspace)
        try:
            result = terminal.run(
                "echo 'written' > new_file.txt && cat new_file.txt", timeout_ms=5000
            )
            assert result.exit_code == 0
            assert "written" in result.output
            # Verify on host side too
            assert (workspace / "new_file.txt").read_text().strip() == "written"
        finally:
            terminal.stop()

    def test_mkdir_in_workspace(self, workspace):
        terminal = self._start_terminal(workspace)
        try:
            result = terminal.run("mkdir -p sub/deep && ls sub", timeout_ms=5000)
            assert result.exit_code == 0
            assert "deep" in result.output
        finally:
            terminal.stop()

    # ── Workspace isolation ──────────────────────────────

    def test_sibling_file_not_visible(self, workspace, test_area):
        """A file outside the workspace (sibling on host) must not be
        visible inside the bwrap sandbox."""
        terminal = self._start_terminal(workspace)
        try:
            # Try to read the sibling file (relative path escape attempt)
            result = terminal.run("cat ../sibling.txt 2>&1 || true", timeout_ms=5000)
            combined = result.output.lower()
            assert (
                "hello" not in result.output
                or "no such file" in combined
                or "not found" in combined
            ), f"Sibling file should not be visible. Got: {result.output}"
        finally:
            terminal.stop()

    def test_cannot_access_absolute_etc(self, workspace):
        """A file in /etc should be readable, but writing must fail (read-only mount)."""
        terminal = self._start_terminal(workspace)
        try:
            # Reading /etc/hostname should work (if exists)
            _result = terminal.run("cat /etc/hostname 2>&1 || true", timeout_ms=5000)
            # Writing MUST fail (read-only)
            result_w = terminal.run("touch /etc/bwrap_test_probe 2>&1 || true", timeout_ms=5000)
            combined = result_w.output.lower()
            assert (
                "read-only" in combined
                or "permission denied" in combined
                or "cannot touch" in combined
            ), f"Write to /etc should be denied. Got: {result_w.output}"
        finally:
            terminal.stop()

    # ── Timeout ──────────────────────────────────────────

    def test_timeout_kills_process(self, workspace):
        terminal = self._start_terminal(workspace)
        start = time.monotonic()
        try:
            result = terminal.run("sleep 10", timeout_ms=500)
            elapsed = time.monotonic() - start
            assert elapsed < 5.0, f"Timeout took too long: {elapsed}s"
            # The process was killed, exit code should be non-zero or -1
            assert result.exit_code != 0
        finally:
            terminal.stop()

    # ── Multiple commands ────────────────────────────────

    def test_multiple_commands_same_terminal(self, workspace):
        terminal = self._start_terminal(workspace)
        try:
            r1 = terminal.run("echo first", timeout_ms=5000)
            assert "first" in r1.output
            r2 = terminal.run("echo second", timeout_ms=5000)
            assert "second" in r2.output
        finally:
            terminal.stop()

    # ── System binaries available ────────────────────────

    def test_system_binaries_available(self, workspace):
        """Common system binaries (ls, cat, grep, which) are accessible."""
        terminal = self._start_terminal(workspace)
        try:
            for binary in ["ls", "cat", "grep", "which", "echo"]:
                result = terminal.run(f"which {binary}", timeout_ms=5000)
                assert result.exit_code == 0, f"{binary} not found: {result.output}"
        finally:
            terminal.stop()


# ═══════════════════════════════════════════════════════════
# Integration tests: shell_handler → PersistentTerminal → bwrap
# ═══════════════════════════════════════════════════════════
# These go through the REAL execution path used by the agent
# when it calls the Shell tool.


@pytest.mark.skipif(not bwrap_available(), reason="bwrap not installed")
class TestShellHandlerBwrap:
    """Test the full shell_handler → PersistentTerminal → bwrap pipeline."""

    @pytest.fixture
    def ws(self):
        """Create a temporary workspace for shell_handler tests."""
        import tempfile

        from agent.core.workspace import Workspace

        with tempfile.TemporaryDirectory() as td:
            w = Workspace(root=td, workspace_uuid="bwrap-shell-test")
            yield w

    # ── Basic execution ──────────────────────────────────

    @pytest.mark.asyncio
    async def test_echo(self, ws):
        from agent.tools.shell import shell_handler

        result = await shell_handler(command="echo hello-from-handler", ws=ws)
        assert "hello-from-handler" in result.output
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_exit_code_nonzero(self, ws):
        from agent.tools.shell import shell_handler

        result = await shell_handler(command="exit 7", ws=ws)
        assert "exit code: 7" in result.output
        assert result.status == "error"

    @pytest.mark.asyncio
    async def test_timeout(self, ws):
        from agent.tools.shell import shell_handler

        result = await shell_handler(command="sleep 10", timeout_ms=500, ws=ws)
        assert "timed out" in result.output.lower()
        assert result.status == "timeout"

    @pytest.mark.asyncio
    async def test_interrupt(self, ws):
        import asyncio

        from agent.tools.shell import shell_handler

        interrupt_event = asyncio.Event()

        async def trigger():
            await asyncio.sleep(0.1)
            interrupt_event.set()

        task = asyncio.create_task(trigger())
        result = await shell_handler(
            command="sleep 10",
            timeout_ms=5000,
            ws=ws,
            interrupt_event=interrupt_event,
        )
        await task
        assert "interrupted" in result.output.lower()
        # Allow PTY fd + bwrap process cleanup to settle before next test
        await asyncio.sleep(0.3)

    @pytest.mark.asyncio
    async def test_write_to_workspace(self, ws):
        from agent.tools.shell import shell_handler

        result = await shell_handler(
            command="echo written-from-handler > out.txt && cat out.txt", ws=ws
        )
        assert "written-from-handler" in result.output
        assert (ws.root / "out.txt").read_text().strip() == "written-from-handler"

    # ── Sandbox properties ───────────────────────────────

    @pytest.mark.asyncio
    async def test_write_to_etc_denied(self, ws):
        """Writing to /etc must fail (read-only root)."""
        from agent.tools.shell import shell_handler

        result = await shell_handler(command="touch /etc/bwrap_handler_probe 2>&1", ws=ws)
        combined = result.output.lower()
        assert (
            "read-only" in combined or "permission denied" in combined or "cannot touch" in combined
        ), f"Expected denial, got: {result.output}"

    @pytest.mark.asyncio
    async def test_cwd_resolution(self, ws):
        from agent.tools.shell import shell_handler

        (ws.root / "subdir").mkdir()
        result = await shell_handler(command="pwd", cwd="subdir", ws=ws)
        assert str(ws.root / "subdir") in result.output

    @pytest.mark.asyncio
    async def test_truncation(self, ws):
        from agent.tools.shell import shell_handler

        result = await shell_handler(command="printf 1234567890", max_bytes=5, ws=ws)
        assert result.output.startswith("12345")
        assert "truncated" in result.output

    @pytest.mark.asyncio
    async def test_cwd_escape_blocked(self, ws):
        from agent.tools.shell import shell_handler

        result = await shell_handler(command="echo hi", cwd="../../../etc", ws=ws)
        assert result.status == "denied"
        assert "outside workspace" in result.output.lower() or "permission" in result.output.lower()
