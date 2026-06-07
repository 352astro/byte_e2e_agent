"""Shell tool — subprocess execution via PTY with async interrupt support.

Architecture (ported from main):
  write_command (sync) → read_stream (executor) + timeout (async) + interrupt (async)
  Three tasks race via asyncio.wait — no polling, no race conditions.
"""

from __future__ import annotations

import asyncio
import contextlib
import queue
import re
import sys
import threading
import time
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agent.tools.result import ToolResult
from agent.tools.terminal import PersistentTerminal
from agent.utils import sysguard

_PLATFORM_MAP = {"linux": "Linux", "darwin": "macOS", "win32": "Windows"}
_PERMISSION_DENIED_PATH_RE = re.compile(r"(?P<path>/[^\s:'\"]+):\s+Permission denied")
_QUOTED_PERMISSION_DENIED_PATH_RE = re.compile(r"['\"](?P<path>/[^'\"]+)['\"]:\s+Permission denied")

# bwrap ENOENT: "ls: cannot access '/foo': No such file or directory"
_ENOENT_PATH_RE = re.compile(
    r"(?P<path>/[^\s:'\"]+):\s+(?:No such file or directory|cannot access)"
)
_ENOENT_QUOTED_RE = re.compile(r"cannot access\s+['\"](?P<path>/[^'\"]+)['\"]")
# bwrap EROFS: "touch: cannot touch '/foo': Read-only file system"
_EROFS_PATH_RE = re.compile(r"(?P<path>/[^\s:'\"]+):\s+Read-only file system")
_EROFS_QUOTED_RE = re.compile(r"['\"](?P<path>/[^'\"]+)['\"]:\s+Read-only file system")
_WRITE_DENIAL_HINTS = (
    "cannot remove",
    "cannot create",
    "cannot write",
    "cannot set",
    "cannot update",
    "failed to create",
    "failed to remove",
    "failed to rename",
    "failed to write",
    "error opening file for download",
    "cleaning up cached downloads",
    "permission denied (os error",
)


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
            "Working directory relative to the workspace root. Use '.' for the workspace root."
        ),
    )
    timeout_ms: int = Field(
        default=30000,
        ge=1000,
        le=120000,
        description="Timeout in milliseconds.",
    )
    max_bytes: int = Field(
        default=20000,
        ge=1000,
        le=200000,
        description="Maximum UTF-8 output bytes to return before truncating.",
    )
    command: str = Field(..., description="Single-line shell command.")


async def shell_handler(
    cwd: str = ".",
    timeout_ms: int = 30000,
    max_bytes: int = 20000,
    command: str = "",
    *,
    ws,
    interrupt_event: asyncio.Event | None = None,
) -> ToolResult:
    """Execute a shell command in the workspace with async interrupt.

    Flow:
      1. Start terminal + write wrapped command (sync, fast).
      2. Read output in executor → async chunks into a queue.
      3. Three async tasks race: chunk reader, timeout timer, interrupt waiter.
      4. On interrupt/timeout: SIGINT to process group, drain, return.
      5. Normal exit: collect all output, return with exit code annotation.
    """
    try:
        workdir = str(ws.resolve(cwd, external_mode="readwrite"))
    except PermissionError as exc:
        return ToolResult(
            f"Error: {exc}",
            status="denied",
            source="sandbox",
            reason=str(exc),
        )
    except Exception as exc:
        return ToolResult(
            f"Error: invalid cwd '{cwd}': {exc}",
            status="error",
            source="tool",
            reason="invalid_cwd",
        )
    if not Path(workdir).is_dir():
        return ToolResult(
            f"Error: cwd is not a directory: {cwd}",
            status="error",
            source="tool",
            reason="cwd_not_directory",
        )

    terminal = PersistentTerminal()
    terminal.start(workdir, sandbox_root=str(ws.root), workspace_uuid=ws.uuid)

    result_queue: queue.Queue[object] = queue.Queue(maxsize=1)
    result_status = "success"
    result_source = "tool"
    result_reason = ""
    output = ""

    def _run_terminal() -> None:
        try:
            result_queue.put_nowait(terminal.run(command, timeout_ms))
        except Exception as exc:
            result_queue.put_nowait(exc)

    thread = threading.Thread(target=_run_terminal, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout_ms / 1000.0

    try:
        interrupted = False
        while True:
            try:
                item = result_queue.get_nowait()
                if isinstance(item, Exception):
                    raise item
                result = item
                output = result.output
                if result.exit_code not in (0, -1):
                    result_status = "error"
                    result_reason = f"exit_code={result.exit_code}"
                    output = (
                        f"{output.rstrip()}\n[exit code: {result.exit_code}]"
                        if output.strip()
                        else f"[exit code: {result.exit_code}]"
                    )
                break
            except queue.Empty:
                pass

            if interrupt_event is not None and interrupt_event.is_set():
                interrupted = True
                result_status = "interrupted"
                result_source = "user"
                result_reason = "interrupted_by_user"
                output = "[Command interrupted]"
                terminal.interrupt()
                break

            if time.monotonic() >= deadline:
                result_status = "timeout"
                result_reason = f"timeout_ms={timeout_ms}"
                output = f"[Command timed out after {timeout_ms}ms]"
                terminal.interrupt()
                break

            await asyncio.sleep(0.02)

        if result_status in {"timeout", "interrupted"}:
            end_wait = time.monotonic() + 2.0
            while time.monotonic() < end_wait:
                try:
                    item = result_queue.get_nowait()
                    if not isinstance(item, Exception) and item.output.strip():
                        output = f"{item.output.rstrip()}\n{output}"
                    break
                except queue.Empty:
                    await asyncio.sleep(0.02)
            if interrupted and not output.strip():
                output = "[Command interrupted]"
            if result_status == "timeout" and "timed out" not in output.lower():
                output = f"{output.rstrip()}\n[Command timed out after {timeout_ms}ms]"
        if thread.is_alive():
            terminal.stop()
    except Exception as exc:
        result_status = "error"
        result_reason = "shell_error"
        output = f"Error: {exc}"
    finally:
        if thread.is_alive():
            with contextlib.suppress(Exception):
                terminal.stop()

    output = output.strip()
    metadata = _sysguard_denial_metadata(output, result_status, result_reason)
    if metadata:
        result_status = "denied"
        result_source = "kernel"
        result_reason = "sysguard_denied"

    raw = output.encode("utf-8", errors="replace")
    if len(raw) > max_bytes:
        omitted = len(raw) - max_bytes
        output = raw[:max_bytes].decode("utf-8", errors="ignore").rstrip()
        output = (
            f"{output}\n[output truncated after {max_bytes} bytes; {omitted} bytes omitted]"
        ).strip()

    return ToolResult(
        output if output else "(no output)",
        status=result_status,
        source=result_source,
        reason=result_reason,
        metadata=metadata,
    )


def _sysguard_denial_metadata(
    output: str,
    status: str,
    reason: str,
) -> dict | None:
    if "[sysguard]" in output:
        return {
            "label": "Sysguard setup",
            "path": "",
            "description": output,
            "confidence": "confirmed",
        }
    if status != "error":
        return None

    write_denial = _looks_like_write_denial(output)

    # ── bwrap / Landlock: Permission denied patterns ─────
    if "Permission denied" in output:
        match = _QUOTED_PERMISSION_DENIED_PATH_RE.search(output)
        if match:
            path = match.group("path")
            candidate = _external_denial_candidate(path, readwrite=write_denial)
            if candidate:
                return candidate

        match = _PERMISSION_DENIED_PATH_RE.search(output)
        if match:
            path = match.group("path")
            candidate = _external_denial_candidate(path, readwrite=write_denial)
            if candidate:
                return candidate

    # ── bwrap: Read-only file system (definite denial) ───
    if "Read-only file system" in output:
        for pat in (_EROFS_PATH_RE, _EROFS_QUOTED_RE):
            match = pat.search(output)
            if match:
                path = match.group("path")
                candidate = _external_denial_candidate(path, readwrite=True)
                if candidate:
                    return candidate
        return None

    # ── bwrap: No such file or directory (suspected missing mount) ──
    if "No such file or directory" in output or "cannot access" in output:
        for pat in (_ENOENT_QUOTED_RE, _ENOENT_PATH_RE):
            match = pat.search(output)
            if match:
                path = match.group("path")
                candidate = _external_denial_candidate(path, readwrite=write_denial)
                if candidate:
                    return candidate
        return None

    return None


def _looks_like_write_denial(output: str) -> bool:
    lowered = output.lower()
    if any(hint in lowered for hint in _WRITE_DENIAL_HINTS):
        return True
    return bool(
        re.search(r"\b(rm|mv|cp|mkdir|touch|install|cargo|rustup|npm|pnpm|yarn)\b", lowered)
    )


def _external_denial_candidate(path: str, *, readwrite: bool) -> dict | None:
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        resolved = Path(path).expanduser().absolute()
    mode = "readwrite" if readwrite else "readonly"
    rule_path = _nearest_rule_path(resolved, readwrite=readwrite)
    if rule_path is None:
        return None
    if sysguard._overlaps_project_root(resolved):
        return None
    if sysguard._overlaps_project_root(rule_path):
        return None
    if sysguard.is_path_allowed(str(resolved), mode):
        return None
    return {
        "label": "Shell external path",
        "path": str(rule_path),
        "denied_path": str(resolved),
        "mode": mode,
        "description": f"Detected denied {mode} access from shell output: {resolved}",
        "confidence": "suspected",
    }


def _nearest_rule_path(path: Path, *, readwrite: bool) -> Path | None:
    if path.exists():
        return path
    if not readwrite:
        return None
    current = path
    while current != current.parent:
        current = current.parent
        if current.exists():
            return current
    return None


shell_tool = StructuredTool.from_function(
    coroutine=shell_handler,
    name="Shell",
    description="Execute a single-line shell command in the workspace.",
    args_schema=ShellInput,
)
