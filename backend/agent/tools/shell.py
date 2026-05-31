"""Shell tool backed by a per-call terminal session."""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from queue import Empty, Queue

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agent.tools.terminal import PersistentTerminal, TerminalResult

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

    command: str = Field(..., description="Single-line shell command.")
    timeout_ms: int = Field(
        default=30000,
        ge=1000,
        le=120000,
        description="Timeout in milliseconds.",
    )


async def shell_handler(
    command: str,
    timeout_ms: int = 30000,
    *,
    ws,
    interrupt_event=None,
) -> str:
    """Execute a shell command in the workspace."""
    terminal = PersistentTerminal()
    cwd = str(getattr(ws, "root", Path.cwd()))
    queue: Queue[TerminalResult | BaseException] = Queue(maxsize=1)
    interrupted = False

    def worker() -> None:
        try:
            terminal.start(cwd)
            queue.put(terminal.run(command, timeout_ms))
        except BaseException as exc:
            queue.put(exc)
        finally:
            terminal.stop()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    while True:
        try:
            item = queue.get_nowait()
            break
        except Empty:
            if interrupt_event is not None and interrupt_event.is_set() and not interrupted:
                interrupted = True
                terminal.interrupt()
            await asyncio.sleep(0.05)

    thread.join(timeout=1)
    if isinstance(item, BaseException):
        return f"Error: {item}"

    output = item.output.strip()
    parts: list[str] = []
    if output:
        parts.append(output)
    if interrupted:
        parts.append("[Command interrupted]")
    elif item.exit_code == -1:
        parts.append(f"[Command timed out after {timeout_ms}ms]")
    elif item.exit_code != 0:
        parts.append(f"[exit code: {item.exit_code}]")
    return "\n".join(parts) if parts else "(no output)"


shell_tool = StructuredTool.from_function(
    coroutine=shell_handler,
    name="Shell",
    description="Execute a single-line shell command in the workspace.",
    args_schema=ShellInput,
)
