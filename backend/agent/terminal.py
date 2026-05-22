"""
持久 Shell 会话 — 跨平台、零外部依赖。

通过 subprocess.Popen + 管道维持长期存活 shell 进程，
用唯一结束标记分割命令输出。每个 SandBox 持有独立实例。

平台适配：
  Linux / macOS  — select + os.read
  Windows        — threading + queue
"""

from __future__ import annotations

import os
import select
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from typing import AsyncIterator, Iterator


@dataclass
class TerminalResult:
    output: str
    exit_code: int = -1


class PersistentTerminal:
    """跨平台持久 shell，通过管道与子进程通信。"""

    def __init__(self, shell: list[str] | None = None) -> None:
        if shell is not None:
            self._shell = shell
        elif sys.platform == "win32":
            self._shell = ["cmd.exe"]
        else:
            self._shell = ["bash", "--norc"]

        self._proc: subprocess.Popen | None = None
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
            self._proc.stdin.close()
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

    def run_stream(self, command: str, timeout_ms: int = 30000) -> Iterator[str]:
        if not self.alive:
            raise RuntimeError("PersistentTerminal not started.")

        marker = f"__TERM_MARK_{uuid.uuid4().hex[:8]}__"
        wrapped = self._build_wrapped(command, marker)
        self._proc.stdin.write(wrapped)
        self._proc.stdin.flush()

        self._last_exit_code = -1
        deadline = time.monotonic() + timeout_ms / 1000.0

        if sys.platform == "win32":
            yield from self._read_stream_win32(marker, deadline)
        else:
            yield from self._read_stream_unix(marker, deadline)

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
                while True:
                    r, _, _ = select.select([self._proc.stdout], [], [], 0.1)
                    if not r:
                        break
                    _ = os.read(self._proc.stdout.fileno(), 4096)
        except Exception:
            pass

    def _build_wrapped(self, command: str, marker: str) -> str:
        if sys.platform == "win32":
            return f"{command} 2>&1\r\necho {marker}%errorlevel%{marker}\r\n"
        else:
            return f"{command} 2>&1; echo {marker}$?{marker}\n"

    def _read_stream_unix(self, marker: str, deadline: float) -> Iterator[str]:
        fd = self._proc.stdout.fileno()
        buf = ""

        while time.monotonic() < deadline:
            r, _, _ = select.select([self._proc.stdout], [], [], 0.05)
            if not r:
                continue

            chunk = os.read(fd, 4096).decode("utf-8", errors="replace")
            if not chunk:
                break

            buf += chunk
            idx = buf.find(marker)
            if idx == -1:
                safe_len = max(0, len(buf) - len(marker))
                if safe_len > 0:
                    yield buf[:safe_len]
                    buf = buf[safe_len:]
            else:
                yield buf[:idx]
                rest = buf[idx + len(marker) :]
                idx2 = rest.find(marker)
                if idx2 != -1:
                    exit_str = rest[:idx2].strip()
                    try:
                        self._last_exit_code = int(exit_str)
                    except ValueError:
                        self._last_exit_code = -1
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
        try:
            while time.monotonic() < deadline:
                try:
                    line = q.get(timeout=0.05)
                except Empty:
                    continue

                buf += line
                idx = buf.find(marker)
                if idx == -1:
                    safe_len = max(0, len(buf) - len(marker))
                    if safe_len > 0:
                        yield buf[:safe_len]
                        buf = buf[safe_len:]
                else:
                    yield buf[:idx]
                    rest = buf[idx + len(marker) :]
                    idx2 = rest.find(marker)
                    if idx2 != -1:
                        exit_str = rest[:idx2].strip()
                        try:
                            self._last_exit_code = int(exit_str)
                        except ValueError:
                            self._last_exit_code = -1
                    break
        finally:
            stop.set()
            t.join(timeout=1)
