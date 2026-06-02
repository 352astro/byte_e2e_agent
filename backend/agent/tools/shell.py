"""Shell tool — subprocess execution via PTY with async interrupt support.

Architecture (ported from main):
  write_command (sync) → read_stream (executor) + timeout (async) + interrupt (async)
  Three tasks race via asyncio.wait — no polling, no race conditions.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agent.tools.terminal import PersistentTerminal

_PLATFORM_MAP = {"linux": "Linux", "darwin": "macOS", "win32": "Windows"}


def get_platform_hint() -> str:
    name = _PLATFORM_MAP.get(sys.platform, sys.platform)
    if sys.platform == "win32":
        return (
            f"Current platform: {name}. "
            "Use cmd.exe commands (dir, type, echo %VAR%, etc.). "
            "Avoid bash-specific syntax (ls, cat, $VAR)."
        )
    return (
        f"Current platform: {name}. "
        "Use Unix shell commands (ls, cat, grep, $VAR, etc.). "
        "Avoid cmd.exe / PowerShell syntax."
    )


class ShellInput(BaseModel):
    """Shell tool input parameters."""

    cwd: str = Field(
        default=".",
        description=(
            "Working directory relative to the workspace root. "
            "Use '.' for the workspace root."
        ),
    )
    timeout_ms: int = Field(
        default=30000,
        ge=1000,
        le=120000,
        description="Timeout in milliseconds.",
    )
    max_output_bytes: int = Field(
        default=20000,
        ge=1000,
        le=200000,
        description="Maximum UTF-8 output bytes to return before truncating.",
    )
    command: str = Field(..., description="Single-line shell command.")


async def shell_handler(
    cwd: str = ".",
    timeout_ms: int = 30000,
    max_output_bytes: int = 20000,
    command: str = "",
    *,
    ws,
    interrupt_event: asyncio.Event | None = None,
) -> str:
    """Execute a shell command in the workspace with async interrupt.

    Flow:
      1. Start terminal + write wrapped command (sync, fast).
      2. Read output in executor → async chunks into a queue.
      3. Three async tasks race: chunk reader, timeout timer, interrupt waiter.
      4. On interrupt/timeout: SIGINT to process group, drain, return.
      5. Normal exit: collect all output, return with exit code annotation.
    """
    loop = asyncio.get_event_loop()
    try:
        workdir = str(ws.resolve(cwd))
    except PermissionError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Error: invalid cwd '{cwd}': {exc}"
    if not Path(workdir).is_dir():
        return f"Error: cwd is not a directory: {cwd}"

    terminal = PersistentTerminal()
    terminal.start(workdir)

    # ── Write command synchronously (fast — no I/O wait) ──
    marker, start_time = terminal.write_command(command)

    # ── Async queue for chunks from the executor thread ──
    chunk_queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _read_task() -> None:
        """Read PTY output in an executor thread, feed chunks into async queue."""

        def _run() -> None:
            try:
                for chunk in terminal.read_stream(marker, start_time, timeout_ms):
                    loop.call_soon_threadsafe(chunk_queue.put_nowait, chunk)
            finally:
                loop.call_soon_threadsafe(chunk_queue.put_nowait, None)

        await loop.run_in_executor(None, _run)

    # ── Trigger: fires on timeout OR user interrupt ──
    trigger = asyncio.Event()
    timed_out = False

    async def _timeout_task() -> None:
        nonlocal timed_out
        await asyncio.sleep(timeout_ms / 1000.0)
        timed_out = True
        trigger.set()

    async def _intr_wait_task() -> None:
        if interrupt_event is None:
            return  # never triggers
        await interrupt_event.wait()
        trigger.set()

    # ── Signal task: on trigger, send SIGINT to foreground process group ──
    interrupted_flag = asyncio.Event()

    async def _signal_task() -> None:
        await trigger.wait()
        terminal.interrupt()
        interrupted_flag.set()

    read_task = asyncio.create_task(_read_task())
    timeout_task = asyncio.create_task(_timeout_task())
    intr_wait_task = asyncio.create_task(_intr_wait_task())
    signal_task = asyncio.create_task(_signal_task())

    output_parts: list[str] = []
    output_bytes = 0
    truncated_bytes = 0

    def append_output(chunk: str) -> None:
        nonlocal output_bytes, truncated_bytes
        if not chunk:
            return
        chunk_bytes = len(chunk.encode("utf-8", errors="replace"))
        remaining = max_output_bytes - output_bytes
        if remaining <= 0:
            truncated_bytes += chunk_bytes
            return
        if chunk_bytes <= remaining:
            output_parts.append(chunk)
            output_bytes += chunk_bytes
            return
        raw = chunk.encode("utf-8", errors="replace")[:remaining]
        output_parts.append(raw.decode("utf-8", errors="ignore"))
        output_bytes = max_output_bytes
        truncated_bytes += chunk_bytes - remaining

    try:
        while not interrupted_flag.is_set():
            chunk_future = asyncio.ensure_future(chunk_queue.get())
            intr_future = asyncio.ensure_future(interrupted_flag.wait())

            done, _ = await asyncio.wait(
                [chunk_future, intr_future],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if chunk_future in done:
                intr_future.cancel()
                chunk = chunk_future.result()
                if chunk is None:
                    break
                append_output(chunk)
            else:
                chunk_future.cancel()

        # ── Interrupted or timed out: drain remaining chunks ──
        if interrupted_flag.is_set():
            while True:
                try:
                    chunk = chunk_queue.get_nowait()
                    if chunk is None:
                        break
                    append_output(chunk)
                except asyncio.QueueEmpty:
                    break

            if timed_out:
                output_parts.append(f"\n[Command timed out after {timeout_ms}ms]")
            else:
                output_parts.append("\n[Command interrupted]")

            # Terminal may be dirty after interrupt — reset for next command
            terminal.stop()

    finally:
        for t in (read_task, timeout_task, intr_wait_task, signal_task):
            if not t.done():
                t.cancel()
        await asyncio.gather(
            read_task,
            timeout_task,
            intr_wait_task,
            signal_task,
            return_exceptions=True,
        )
        # Ensure terminal is stopped if not already
        try:
            terminal.stop()
        except Exception:
            pass

    output = "".join(output_parts).strip()
    if truncated_bytes > 0:
        output = (
            f"{output}\n[output truncated after {max_output_bytes} bytes; "
            f"{truncated_bytes} bytes omitted]"
        ).strip()

    # ── Append exit code for non-zero (normal exit path only) ──
    if not interrupted_flag.is_set():
        exit_code = terminal._last_exit_code
        if exit_code not in (0, -1):
            if output:
                output += f"\n[exit code: {exit_code}]"
            else:
                output = f"[exit code: {exit_code}]"

    return output if output else "(no output)"


shell_tool = StructuredTool.from_function(
    coroutine=shell_handler,
    name="Shell",
    description="Execute a single-line shell command in the workspace.",
    args_schema=ShellInput,
)
