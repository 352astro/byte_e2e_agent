"""
持久 Shell 会话 — 跨平台。

Linux / macOS  — PTY (os.openpty) + select + os.read
                信号通过 os.killpg 精准送达前台进程组
Windows        — threading + queue (pipe)

用法不变：run_stream() / run() / alive / start / stop。
"""

from __future__ import annotations

import os
import re
import select
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from typing import AsyncIterator, Iterator

if sys.platform != "win32":
    import termios


@dataclass
class TerminalResult:
    output: str
    exit_code: int = -1


# ── ANSI escape stripping ──────────────────────────────

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\x1b\][0-9;]*\x1b\\\\")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from terminal output."""
    return _ANSI_RE.sub("", text)


class PersistentTerminal:
    """跨平台持久 shell — Unix 使用 PTY, Windows 使用 pipe。"""

    def __init__(self, shell: list[str] | None = None) -> None:
        if shell is not None:
            self._shell = shell
        elif sys.platform == "win32":
            self._shell = ["cmd.exe"]
        else:
            self._shell = ["bash", "--norc"]

        self._proc: subprocess.Popen | None = None
        self._master_fd: int | None = None  # PTY master (Unix only)
        self._cwd: str = ""
        self._last_exit_code: int = -1

    # ── 生命周期 ──────────────────────────────────────

    def start(self, cwd: str = ".") -> None:
        if self._proc is not None:
            self.stop()

        self._cwd = os.path.abspath(cwd)
        env = os.environ.copy()
        if sys.platform != "win32":
            env["TERM"] = "dumb"

        if sys.platform == "win32":
            self._start_win32(env)
        else:
            self._start_unix(env)

    def _start_unix(self, env: dict) -> None:
        master_fd, slave_fd = os.openpty()

        # Disable echo on the slave side so our commands don't echo back
        attrs = termios.tcgetattr(slave_fd)
        attrs[3] &= ~termios.ECHO  # local flags: clear ECHO
        termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)

        self._proc = subprocess.Popen(
            self._shell,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=self._cwd,
            env=env,
            preexec_fn=os.setsid,  # new session → own process group
        )
        os.close(slave_fd)  # child inherited it, parent doesn't need it
        self._master_fd = master_fd
        self._drain_startup()

    def _start_win32(self, env: dict) -> None:
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
        try:
            if self._master_fd is not None:
                os.close(self._master_fd)
                self._master_fd = None
        except Exception:
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ── 命令执行 ──────────────────────────────────────

    def run(self, command: str, timeout_ms: int = 30000) -> TerminalResult:
        parts: list[str] = []
        for chunk in self.run_stream(command, timeout_ms):
            parts.append(chunk)
        return TerminalResult(output="".join(parts), exit_code=self._last_exit_code)

    def write_command(self, command: str) -> tuple[str, float]:
        """Write a command to stdin, return (marker, deadline_ms).

        Call this before read_stream() so the command starts immediately
        and the caller can signal readiness before blocking on I/O.
        """
        if not self.alive:
            raise RuntimeError("PersistentTerminal not started.")
        marker = f"__TERM_MARK_{uuid.uuid4().hex[:8]}__"
        wrapped = self._build_wrapped(command, marker)
        self._write_stdin(wrapped)
        self._last_exit_code = -1
        return marker, time.monotonic()

    def read_stream(
        self, marker: str, start_time: float, timeout_ms: int = 30000
    ) -> Iterator[str]:
        """Read command output until the marker is found or timeout.

        Must be called after write_command(); the command is already running.
        """
        deadline = start_time + timeout_ms / 1000.0
        marker_found = False

        if sys.platform == "win32":
            for chunk in self._read_stream_win32(marker, deadline):
                yield chunk
            marker_found = self._last_exit_code != -1
        else:
            for chunk in self._read_stream_unix(marker, deadline):
                yield chunk
            marker_found = self._last_exit_code != -1

        if not marker_found and self.alive:
            self._recover_after_timeout()

    def run_stream(self, command: str, timeout_ms: int = 30000) -> Iterator[str]:
        """Convenience: write + read in one call (backward-compatible)."""
        marker, start = self.write_command(command)
        yield from self.read_stream(marker, start, timeout_ms)

    def interrupt(self) -> None:
        """Send SIGINT to the foreground process group.

        Unlike _recover_after_timeout, does NOT drain output —
        the worker thread's _read_stream_unix will catch the
        marker and finish naturally.
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

    def get_cwd(self) -> str:
        if not self.alive:
            return self._cwd
        if sys.platform == "win32":
            result = self.run("echo %cd%", timeout_ms=2000)
        else:
            result = self.run("pwd", timeout_ms=2000)
        cwd = result.output.strip()
        if cwd:
            self._cwd = cwd
        return self._cwd or self._cwd

    # ── 内部 ──────────────────────────────────────────

    def _write_stdin(self, data: str) -> None:
        """Write data to the shell's stdin, platform-appropriate."""
        if sys.platform == "win32":
            assert self._proc is not None
            self._proc.stdin.write(data)
            self._proc.stdin.flush()
        else:
            assert self._master_fd is not None
            os.write(self._master_fd, data.encode("utf-8"))

    def _read_fd(self) -> int:
        """Return the file descriptor to read from."""
        if sys.platform == "win32":
            return self._proc.stdout.fileno()
        else:
            assert self._master_fd is not None
            return self._master_fd

    def _drain_startup(self) -> None:
        if self._proc is None:
            return
        time.sleep(0.3)
        try:
            if sys.platform == "win32":
                import msvcrt

                old = os.dup(self._proc.stdout.fileno())
                os.set_blocking(self._proc.stdout.fileno(), False)
                try:
                    _ = self._proc.stdout.read(4096)
                except Exception:
                    pass
                os.set_blocking(self._proc.stdout.fileno(), True)
            else:
                fd = self._master_fd
                assert fd is not None
                while True:
                    r, _, _ = select.select([fd], [], [], 0.1)
                    if not r:
                        break
                    os.read(fd, 4096)
        except Exception:
            pass

    def _recover_after_timeout(self) -> None:
        """Interrupt the stuck process, drain output, sync terminal.

        After SIGINT bash outputs a fresh prompt.  We drain passive output
        first, then write a sync marker and read until it appears — this
        consumes the prompt so the next command's marker detection is clean.
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
        else:
            return f"{command} 2>&1; echo {marker}$?{marker}\n"

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
                    # Found opening marker — yield command output
                    yield buf[:idx]
                    first_marker_found = True
                    buf = buf[idx + len(marker) :]  # keep exit_code + closing marker

            if first_marker_found:
                idx2 = buf.find(marker)
                if idx2 != -1:
                    # Found closing marker — parse exit code
                    exit_str = buf[:idx2].strip()
                    try:
                        self._last_exit_code = int(exit_str)
                    except ValueError:
                        self._last_exit_code = 0  # marker found, exit code unreadable
                    break

    def _read_stream_win32(self, marker: str, deadline: float) -> Iterator[str]:
        import threading
        from queue import Empty, Queue

        q: Queue = Queue()
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
                            self._last_exit_code = (
                                0  # marker found, exit code unreadable
                            )
                        break
        finally:
            stop.set()
            t.join(timeout=1)
