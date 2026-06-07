"""Per-call terminal runner for the Shell tool."""

from __future__ import annotations

import os
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

if sys.platform != "win32":
    import termios

import contextlib

from agent.utils import sandbox


@dataclass
class TerminalResult:
    output: str
    exit_code: int = -1


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\x1b\][0-9;]*\x1b\\\\")
_PROMPT_RE = re.compile(r"(?m)^(?:>+\s*)?(?:bash-[\d.]+\$|sh-\d+\.\d+\$)\s*$")


def _strip_ansi(text: str) -> str:
    cleaned = _ANSI_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _PROMPT_RE.sub("", cleaned)
    return cleaned.replace("\n\n", "\n")


class PersistentTerminal:
    """Cross-platform shell session.

    Shell tool uses this as a one-shot runner: start, run one command, stop.
    The implementation is intentionally stateful so marker-based command
    completion, PTY behavior, timeout recovery, and interrupts stay robust.
    """

    def __init__(self, shell: list[str] | None = None) -> None:
        if shell is not None:
            self._shell = shell
        elif sys.platform == "win32":
            self._shell = ["cmd.exe"]
        else:
            self._shell = ["bash", "--norc"]

        self._proc: subprocess.Popen | None = None
        self._master_fd: int | None = None
        self._cwd = ""
        self._sandbox_root = ""
        self._seatbelt_profile_path: str | None = None
        self._blackhole_dir: str | None = None
        self._last_exit_code = -1

    def start(
        self,
        cwd: str = ".",
        *,
        sandbox_root: str | None = None,
        workspace_uuid: str | None = None,
    ) -> None:
        if self._proc is not None:
            self.stop()

        self._cwd = os.path.abspath(cwd)
        self._sandbox_root = os.path.abspath(sandbox_root or self._cwd)
        env = os.environ.copy()
        if workspace_uuid:
            env["AGENT_WORKSPACE_UUID"] = workspace_uuid
        backend_root = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = (
            f"{backend_root}{os.pathsep}{env['PYTHONPATH']}"
            if env.get("PYTHONPATH")
            else backend_root
        )
        if sys.platform != "win32":
            env["TERM"] = "dumb"
        venv = env.get("VIRTUAL_ENV")
        if venv:
            try:
                Path(venv).resolve().relative_to(backend_root)
                env.pop("VIRTUAL_ENV", None)
                path_parts = env.get("PATH", "").split(os.pathsep)
                venv_bin = str(Path(venv).resolve() / "bin")
                env["PATH"] = os.pathsep.join(
                    part for part in path_parts if part and part != venv_bin
                )
            except ValueError:
                pass

        if sys.platform == "win32":
            self._start_win32(env)
        else:
            self._start_unix(env)

    def _start_unix(self, env: dict[str, str]) -> None:
        master_fd, slave_fd = os.openpty()
        attrs = termios.tcgetattr(slave_fd)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)

        shell_cmd = list(self._shell)
        if sys.platform == "darwin":
            if sandbox.seatbelt_available():
                profile = sandbox.build_seatbelt_profile(
                    self._sandbox_root,
                    workspace_uuid=env.get("AGENT_WORKSPACE_UUID"),
                )
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".sb",
                    delete=False,
                    encoding="utf-8",
                ) as tmpf:
                    tmpf.write(profile)
                self._seatbelt_profile_path = tmpf.name
                shell_cmd = ["sandbox-exec", "-f", tmpf.name, "--", *shell_cmd]
        elif sys.platform == "linux":
            if not sandbox.bwrap_available():
                raise RuntimeError(
                    "bwrap (bubblewrap) is required for Linux sandbox. "
                    "Install with: apt-get install bubblewrap"
                )
            shell_cmd, blackhole = sandbox.build_bwrap_cmd(
                self._sandbox_root,
                self._shell,
                workspace_uuid=env.get("AGENT_WORKSPACE_UUID"),
            )
            self._blackhole_dir = blackhole

        self._proc = subprocess.Popen(
            shell_cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=self._cwd,
            env=env,
            start_new_session=True,
        )
        os.close(slave_fd)
        self._master_fd = master_fd
        self._drain_startup()

    def _start_win32(self, env: dict[str, str]) -> None:
        self._proc = subprocess.Popen(
            self._shell,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=self._cwd,
            env=env,
        )
        self._drain_startup()

    def stop(self) -> None:
        if self._proc is None:
            return
        proc = self._proc
        try:
            if sys.platform != "win32":
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
            else:
                proc.terminate()
            proc.wait(timeout=1)
        except Exception:
            try:
                if sys.platform != "win32":
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGKILL)
                else:
                    proc.kill()
                proc.wait(timeout=1)
            except Exception:
                pass
        try:
            if self._master_fd is not None:
                os.close(self._master_fd)
                self._master_fd = None
        except Exception:
            pass
        self._proc = None
        if self._seatbelt_profile_path:
            with contextlib.suppress(OSError):
                os.unlink(self._seatbelt_profile_path)
            self._seatbelt_profile_path = None
        if self._blackhole_dir:
            with contextlib.suppress(OSError):
                shutil.rmtree(self._blackhole_dir, ignore_errors=True)
            self._blackhole_dir = None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def run(self, command: str, timeout_ms: int = 30000) -> TerminalResult:
        parts: list[str] = []
        for chunk in self.run_stream(command, timeout_ms):
            parts.append(chunk)
        return TerminalResult(output="".join(parts), exit_code=self._last_exit_code)

    def write_command(self, command: str) -> tuple[str, float]:
        if not self.alive:
            raise RuntimeError("PersistentTerminal not started.")
        marker = f"__TERM_MARK_{uuid.uuid4().hex[:8]}__"
        self._write_stdin(self._build_wrapped(command, marker))
        self._last_exit_code = -1
        return marker, time.monotonic()

    def read_stream(self, marker: str, start_time: float, timeout_ms: int = 30000) -> Iterator[str]:
        deadline = start_time + timeout_ms / 1000.0

        if sys.platform == "win32":
            yield from self._read_stream_win32(marker, deadline)
        else:
            yield from self._read_stream_unix(marker, deadline)

        if self._last_exit_code == -1 and self.alive:
            self._recover_after_timeout()

    def run_stream(self, command: str, timeout_ms: int = 30000) -> Iterator[str]:
        marker, start = self.write_command(command)
        yield from self.read_stream(marker, start, timeout_ms)

    def interrupt(self) -> None:
        """Send SIGINT to the foreground process group.

        os.killpg is intentional here: SIGINT must reach both the shell
        AND the foreground job (e.g. sleep). os.kill would only target
        the shell process, which may not forward the signal in
        non-interactive mode, causing the interrupt to silently fail.
        """
        if not self.alive:
            return
        try:
            if sys.platform == "win32":
                self._write_stdin("\x03")
            else:
                assert self._proc is not None
                pgid = os.getpgid(self._proc.pid)
                os.killpg(pgid, signal.SIGINT)
        except Exception:
            pass

    def _write_stdin(self, data: str) -> None:
        if sys.platform == "win32":
            assert self._proc is not None and self._proc.stdin is not None
            self._proc.stdin.write(data)
            self._proc.stdin.flush()
        else:
            assert self._master_fd is not None
            os.write(self._master_fd, data.encode("utf-8"))

    def _drain_startup(self) -> None:
        if self._proc is None:
            return
        time.sleep(0.2)
        try:
            if sys.platform == "win32":
                assert self._proc.stdout is not None
                fd = self._proc.stdout.fileno()
                os.set_blocking(fd, False)
                with contextlib.suppress(Exception):
                    self._proc.stdout.read(4096)
                os.set_blocking(fd, True)
            else:
                fd = self._master_fd
                assert fd is not None
                while True:
                    r, _, _ = select.select([fd], [], [], 0.05)
                    if not r:
                        break
                    os.read(fd, 4096)
        except Exception:
            pass

    def _recover_after_timeout(self) -> None:
        """Interrupt the stuck process, drain output, sync terminal.

        Uses os.killpg intentionally — same reason as interrupt().
        """
        if not self.alive:
            return
        try:
            if sys.platform == "win32":
                self._write_stdin("\x03")
                time.sleep(0.3)
            else:
                assert self._proc is not None
                pgid = os.getpgid(self._proc.pid)
                os.killpg(pgid, signal.SIGINT)
                time.sleep(0.3)
                self._drain_startup()
        except Exception:
            pass

    def _build_wrapped(self, command: str, marker: str) -> str:
        if sys.platform == "win32":
            return f"{command} 2>&1\r\necho {marker}%errorlevel%{marker}\r\n"
        return (
            f"({command}) 2>&1; "
            "__term_status=$?; "
            f"printf '\\n{marker}%s{marker}\\n' \"$__term_status\"\n"
        )

    def _read_stream_unix(self, marker: str, deadline: float) -> Iterator[str]:
        fd = self._master_fd
        assert fd is not None
        buf = ""
        first_marker_found = False

        while time.monotonic() < deadline:
            r, _, _ = select.select([fd], [], [], 0.05)
            if not r:
                continue

            raw = os.read(fd, 4096).decode("utf-8", errors="replace")
            if not raw:
                break
            chunk = _strip_ansi(raw)
            if not chunk:
                continue

            buf += chunk

            if not first_marker_found:
                idx = buf.find(marker)
                if idx == -1:
                    safe_len = max(0, len(buf) - len(marker))
                    if safe_len > 0:
                        yield buf[:safe_len]
                        buf = buf[safe_len:]
                else:
                    yield buf[:idx]
                    first_marker_found = True
                    buf = buf[idx + len(marker) :]

            if first_marker_found:
                idx2 = buf.find(marker)
                if idx2 != -1:
                    exit_str = buf[:idx2].strip()
                    try:
                        self._last_exit_code = int(exit_str)
                    except ValueError:
                        self._last_exit_code = 0
                    break

    def _read_stream_win32(self, marker: str, deadline: float) -> Iterator[str]:
        import threading
        from queue import Empty, Queue

        assert self._proc is not None and self._proc.stdout is not None
        q: Queue[str] = Queue()
        stop = threading.Event()

        def _reader() -> None:
            while not stop.is_set():
                try:
                    line = self._proc.stdout.readline()
                    if line:
                        q.put(line)
                    else:
                        break
                except Exception:
                    break

        t = threading.Thread(target=_reader, daemon=True)
        t.start()

        buf = ""
        first_marker_found = False
        try:
            while time.monotonic() < deadline:
                try:
                    line = q.get(timeout=0.05)
                except Empty:
                    continue

                buf += line

                if not first_marker_found:
                    idx = buf.find(marker)
                    if idx == -1:
                        safe_len = max(0, len(buf) - len(marker))
                        if safe_len > 0:
                            yield buf[:safe_len]
                            buf = buf[safe_len:]
                    else:
                        yield buf[:idx]
                        first_marker_found = True
                        buf = buf[idx + len(marker) :]

                if first_marker_found:
                    idx2 = buf.find(marker)
                    if idx2 != -1:
                        exit_str = buf[:idx2].strip()
                        try:
                            self._last_exit_code = int(exit_str)
                        except ValueError:
                            self._last_exit_code = 0
                        break
        finally:
            stop.set()
            t.join(timeout=1)
