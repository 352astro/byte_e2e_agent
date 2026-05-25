"""
沙箱 — 多会话隔离容器。

每个 ReActAgent 实例持有一个 SandBox，负责：
- 持久终端管理（PersistentTerminal）
- 路径越界审查（safe_resolve_path）
- 危险指令拦截（check_command_safety）
- 可执行工具的分流执行（Shell / Read / Write / Edit / Search / LoadSkill）

不处理 Plan / SubTask —— 这些由 react 循环直接拦截。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from agent.terminal import PersistentTerminal, TerminalResult
from agent.utils.safety import check_command_safety, safe_resolve_path


class SandBox:
    """每个 agent 实例独立的执行环境。"""

    def __init__(self, workspace: str | Path = ".", session_id: str | None = None) -> None:
        self._workspace = os.path.abspath(str(workspace))
        self._session_id = session_id
        self._terminal: PersistentTerminal | None = None
        os.makedirs(self._workspace, exist_ok=True)

    # ── 属性 ──────────────────────────────────────────

    @property
    def workspace(self) -> str:
        return self._workspace

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def terminal(self) -> PersistentTerminal:
        if self._terminal is None or not self._terminal.alive:
            self._terminal = PersistentTerminal()
            self._terminal.start(self._workspace)
        return self._terminal

    # ── 生命周期 ──────────────────────────────────────

    async def shutdown(self) -> None:
        if self._terminal is not None:
            self._terminal.stop()
            self._terminal = None

    # ── 路径审查 ──────────────────────────────────────

    def resolve_path(self, relpath: str) -> str:
        """安全检查 + 解析为绝对路径。"""
        return safe_resolve_path(relpath, self._workspace)

    # ── Shell ─────────────────────────────────────────

    async def run_shell(self, command: str, timeout_ms: int = 30000) -> str:
        """在持久终端中执行命令，返回格式化结果。"""
        try:
            check_command_safety(command)
        except ValueError as exc:
            return f"Error: {exc}"

        try:
            result: TerminalResult = self.terminal.run(command, timeout_ms)
        except Exception as exc:
            return f"Error: {exc}"

        parts: list[str] = []
        if result.output.strip():
            parts.append(result.output.rstrip())
        if result.exit_code != 0:
            parts.append(f"[exit code: {result.exit_code}]")
        return "\n".join(parts) if parts else "(no output)"

    async def stream_shell(
        self, command: str, timeout_ms: int = 30000,
        interrupt_event: asyncio.Event | None = None,
    ):
        """流式执行 Shell 命令，yield 输出块。

        无 interrupt_event 时走同步路径（零线程开销）。
        有 interrupt_event 时在后台线程运行终端 I/O，保持 event loop
        空闲以响应中断。
        """
        try:
            check_command_safety(command)
        except ValueError as exc:
            yield f"Error: {exc}"
            return

        # ── 无中断需求：同步路径，零额外开销 ──────────
        if interrupt_event is None:
            for chunk in self.terminal.run_stream(command, timeout_ms):
                yield chunk
            return

        # ── 可中断路径：terminal 在 background task，外层 asyncio.wait 竞速 ──
        loop = asyncio.get_event_loop()
        chunk_queue: asyncio.Queue[str | None] = asyncio.Queue()
        interrupted = asyncio.Event()

        # 1. Write command synchronously (fast, no blocking)
        marker, start_time = self.terminal.write_command(command)

        # 2. Background task: read output in thread, feed chunks to queue
        async def _read_task() -> None:
            def _run() -> None:
                try:
                    for chunk in self.terminal.read_stream(marker, start_time, timeout_ms):
                        loop.call_soon_threadsafe(chunk_queue.put_nowait, chunk)
                finally:
                    loop.call_soon_threadsafe(chunk_queue.put_nowait, None)
            await loop.run_in_executor(None, _run)

        read_task = asyncio.create_task(_read_task())

        # 3. Fuse timeout + user interrupt into a single trigger
        trigger = asyncio.Event()

        async def _timeout_task() -> None:
            await asyncio.sleep(timeout_ms / 1000.0)
            trigger.set()

        async def _user_intr_task() -> None:
            await interrupt_event.wait()
            trigger.set()

        asyncio.create_task(_timeout_task())
        asyncio.create_task(_user_intr_task())

        # 4. Background task: on trigger, SIGINT, signal done
        async def _interrupt_task() -> None:
            await trigger.wait()
            self.terminal.interrupt()
            interrupted.set()

        asyncio.create_task(_interrupt_task())

        asyncio.create_task(_interrupt_task())

        try:
            while not interrupted.is_set():
                # Race: next chunk vs interrupt signal
                chunk_future = asyncio.ensure_future(chunk_queue.get())
                intr_future = asyncio.ensure_future(interrupted.wait())
                done, _ = await asyncio.wait(
                    [chunk_future, intr_future],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # Cancel the loser
                if chunk_future in done:
                    intr_future.cancel()
                    chunk = chunk_future.result()
                    if chunk is None:
                        break
                    yield chunk
                else:
                    chunk_future.cancel()
            # Interrupted: drain remaining chunks
            while True:
                try:
                    chunk = chunk_queue.get_nowait()
                    if chunk is None:
                        break
                    yield chunk
                except asyncio.QueueEmpty:
                    break
        finally:
            if not read_task.done():
                read_task.cancel()
            await asyncio.gather(read_task, return_exceptions=True)

    # ── Read ──────────────────────────────────────────

    async def read_file(self, path: str) -> str:
        try:
            safe_path = self.resolve_path(path)
        except ValueError as exc:
            return f"Error: {exc}"
        try:
            with open(safe_path, encoding="utf-8") as fh:
                content = fh.read()
            return content if content else "(empty)"
        except FileNotFoundError:
            return f"Error: file not found '{path}'"
        except IsADirectoryError:
            return f"Error: '{path}' is a directory, not a file"
        except PermissionError:
            return f"Error: permission denied reading '{path}'"
        except UnicodeDecodeError:
            try:
                with open(safe_path, "rb") as fh:
                    raw = fh.read()
                return f"[binary file, {len(raw)} bytes, preview]\n{raw[:200]!r}"
            except Exception as exc:
                return f"Error: cannot read binary file '{path}': {exc}"
        except Exception as exc:
            return f"Error: {exc}"

    # ── Write ─────────────────────────────────────────

    async def write_file(self, path: str, content: str) -> str:
        try:
            safe_path = self.resolve_path(path)
        except ValueError as exc:
            return f"Error: {exc}"
        try:
            parent = os.path.dirname(safe_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(safe_path, "w", encoding="utf-8") as fh:
                fh.write(content)
            return f"Successfully wrote {path} ({len(content)} characters)"
        except PermissionError:
            return f"Error: permission denied writing '{path}'"
        except IsADirectoryError:
            return f"Error: '{path}' is an existing directory, cannot write as file"
        except Exception as exc:
            return f"Error: {exc}"

    # ── Edit ──────────────────────────────────────────

    async def edit_file(self, path: str, edits: list[dict]) -> str:
        """执行一系列查找替换操作。edits: [{old_text, new_text}, ...]"""
        from agent.tools.edit import _fuzzy_replace, _snippet_around

        try:
            safe_path = self.resolve_path(path)
        except ValueError as exc:
            return f"Error: {exc}"

        try:
            with open(safe_path, encoding="utf-8") as fh:
                content = fh.read()
        except FileNotFoundError:
            return (
                f"Error: file not found '{path}'. Use Write to create a new file first."
            )
        except IsADirectoryError:
            return f"Error: '{path}' is a directory, not a file"
        except PermissionError:
            return f"Error: permission denied reading '{path}'"
        except UnicodeDecodeError:
            return f"Error: '{path}' appears to be a binary file; cannot edit"
        except Exception as exc:
            return f"Error: {exc}"

        original = content
        for i, op in enumerate(edits):
            new_content, found = _fuzzy_replace(content, op["old_text"], op["new_text"])
            if not found:
                snippet = _snippet_around(original, op["old_text"])
                return (
                    f"Error: edit #{i + 1} failed -- cannot find old_text in '{path}'.\n"
                    f"--- old_text ---\n{op['old_text']}\n"
                    f"--- file excerpt ---\n{snippet}\n"
                    f"Hint: re-Read the file to get the exact current content."
                )
            content = new_content

        try:
            with open(safe_path, "w", encoding="utf-8") as fh:
                fh.write(content)
        except PermissionError:
            return f"Error: permission denied writing '{path}'"
        except Exception as exc:
            return f"Error: {exc}"

        return f"Successfully applied {len(edits)} edit(s) to {path}."
