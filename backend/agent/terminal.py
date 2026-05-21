"""
持久 Shell 会话 — 跨平台、零外部依赖。

Agent 的 Bash 工具需要可累积状态的终端（cd / ls 等前后关联）。
本模块提供一个 PersistentTerminal 类，内部用 subprocess.Popen + 管道
维持一个长期存活 shell 进程，通过唯一结束标记分割命令输出。

平台适配：
  Linux / macOS  — select + os.read    （单线程非阻塞）
  Windows        — threading + queue   （管道不支持 select）
  对外接口统一为 Iterator[str]。

异步扩展路径：
  subprocess.Popen → asyncio.create_subprocess_shell
  select           → asyncio event loop
  接口签名无需改变，新增 async run_stream_async() 即可。
"""

from __future__ import annotations

import os
import select
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

# ── 结果模型 ──────────────────────────────────────────


@dataclass
class TerminalResult:
    output: str
    exit_code: int = -1


# ── 模块级单例 ────────────────────────────────────────

_terminal: PersistentTerminal | None = None


def set_terminal(t: PersistentTerminal) -> None:
    global _terminal
    _terminal = t


def get_terminal() -> PersistentTerminal:
    if _terminal is None:
        raise RuntimeError("PersistentTerminal not initialised.")
    return _terminal


def reset_terminal() -> None:
    global _terminal
    if _terminal is not None:
        _terminal.stop()
    _terminal = None


# ── PersistentTerminal ────────────────────────────────


class PersistentTerminal:
    """跨平台持久 shell，通过管道与子进程通信。

    用法:
        t = PersistentTerminal()
        t.start("/tmp/workspace")
        out = t.run("ls -la")          # 阻塞式
        for chunk in t.run_stream("ls -la"):
            print(chunk, end="")       # 流式
        t.stop()
    """

    def __init__(self, shell: list[str] | None = None) -> None:
        if shell is not None:
            self._shell = shell
        elif sys.platform == "win32":
            self._shell = ["cmd.exe"]
        else:
            self._shell = ["bash", "--norc"]

        self._proc: subprocess.Popen | None = None
        self._cwd: str = ""

    # ── 生命周期 ──────────────────────────────────────

    def start(self, cwd: str = ".") -> None:
        """启动持久 shell 进程。"""
        if self._proc is not None:
            self.stop()

        self._cwd = os.path.abspath(cwd)

        env = os.environ.copy()
        if sys.platform != "win32":
            env["TERM"] = "dumb"  # 禁用 ANSI 颜色

        self._proc = subprocess.Popen(
            self._shell,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=self._cwd,
            env=env,
        )

        # 吃掉启动输出（bash 欢迎语、cmd 版权声明等）
        self._drain_startup()

    def stop(self) -> None:
        """关闭 shell 进程。"""
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
        """阻塞执行命令，返回完整结果。"""
        parts: list[str] = []
        exit_code = -1
        for chunk in self.run_stream(command, timeout_ms):
            parts.append(chunk)
            # run_stream 的最后一个 chunk 可能是 exit_code（由 _build_wrapped 控制）
        # run_stream 内部已通过队列传出 exit_code，这里重建结果
        output = "".join(parts)
        # 从 run_stream 获取的流不包含 exit_code，它是通过内部机制传递的
        # 简化：run_stream 不暴露 exit_code，run 需要另取
        exit_code = self._last_exit_code
        return TerminalResult(output=output, exit_code=exit_code)

    def run_stream(self, command: str, timeout_ms: int = 30000) -> Iterator[str]:
        """流式执行命令，逐块 yield stdout。

        最后一个 yielded 值之后，可通过 ``_last_exit_code`` 获取退出码。
        """
        if not self.alive:
            raise RuntimeError("PersistentTerminal not started.")

        # 生成唯一标记
        marker = f"__TERM_MARK_{uuid.uuid4().hex[:8]}__"

        # 构建包装命令：在末尾追加 "echo <marker>$?<marker>"
        wrapped = self._build_wrapped(command, marker)

        self._proc.stdin.write(wrapped)
        self._proc.stdin.flush()

        output_parts: list[str] = []
        self._last_exit_code = -1
        deadline = time.monotonic() + timeout_ms / 1000.0

        if sys.platform == "win32":
            yield from self._read_stream_win32(marker, deadline)
        else:
            yield from self._read_stream_unix(marker, deadline)

    # ── cwd 查询 ──────────────────────────────────────

    def get_cwd(self) -> str:
        """查询 shell 当前工作目录。"""
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
        """读取并丢弃 shell 启动期间的输出（bashrc、cmd 版权等）。"""
        if self._proc is None:
            return
        time.sleep(0.3)  # 等待 shell 初始化
        try:
            if sys.platform == "win32":
                # 一次性读取当前缓冲区
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
        """将命令包装为可被标记检测的形式。"""
        if sys.platform == "win32":
            return f"{command} 2>&1\r\necho {marker}%errorlevel%{marker}\r\n"
        else:
            return f"{command} 2>&1; echo {marker}$?{marker}\n"

    def _read_stream_unix(self, marker: str, deadline: float) -> Iterator[str]:
        """Unix 流式读取（select + os.read）。"""
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

            # 检测标记
            idx = buf.find(marker)
            if idx == -1:
                # 没有标记 → 全部可以 yield
                # 但保留末尾可能被截断的 marker 前缀（最多 len(marker)-1 字符）
                safe_len = max(0, len(buf) - len(marker))
                if safe_len > 0:
                    yield buf[:safe_len]
                    buf = buf[safe_len:]
            else:
                # 找到第一个 marker
                # 前半部分是输出
                yield buf[:idx]
                # 两个 marker 之间是 exit code
                rest = buf[idx + len(marker) :]
                idx2 = rest.find(marker)
                if idx2 != -1:
                    exit_str = rest[:idx2].strip()
                    try:
                        self._last_exit_code = int(exit_str)
                    except ValueError:
                        self._last_exit_code = -1
                    # 后半部分（第二个 marker 之后）是 shell 提示符，丢弃
                break

    def _read_stream_win32(self, marker: str, deadline: float) -> Iterator[str]:
        """Windows 流式读取（threading + queue）。"""
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
