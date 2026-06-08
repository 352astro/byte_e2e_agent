"""PyRepl tool — sandboxed Python subprocess execution.

Runs user code in an isolated subprocess. Python semantics are normal
(stdlib imports, project dependencies from the current venv, open(), etc.);
filesystem restrictions come from the same OS-level sandbox used by Shell.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import signal
import sys
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agent.tools.result import ToolResult
from agent.utils import sandbox

_MAX_OUTPUT_BYTES = 20_000
_DEFAULT_TIMEOUT_S = 30
_SANDBOX_VENV = "/tmp/.venv"


class PyReplInput(BaseModel):
    """PyRepl 工具输入参数。"""

    timeout_ms: int = Field(
        default=30000,
        ge=1000,
        le=60000,
        description="Timeout in milliseconds.",
    )
    code: str = Field(
        ...,
        description=(
            "Python code to execute in a subprocess sandbox. Standard library "
            "imports and normal Python I/O are available; filesystem writes "
            "are constrained by the workspace sandbox."
        ),
    )


def _current_venv_root() -> Path | None:
    prefix = Path(sys.prefix).resolve()
    if sys.prefix == sys.base_prefix:
        return None
    if not (prefix / "pyvenv.cfg").exists():
        return None
    return prefix


def _sandbox_python(venv_root: Path | None) -> str:
    if venv_root is None:
        return sys.executable
    executable = Path(sys.executable)
    try:
        rel = executable.relative_to(venv_root)
    except ValueError:
        rel = Path("bin") / executable.name
    return str(Path(_SANDBOX_VENV) / rel)


def _build_command(
    code: str,
    *,
    sandbox_root: str,
    workspace_uuid: str | None,
) -> tuple[list[str], str | None]:
    venv_root = _current_venv_root()
    python = _sandbox_python(venv_root)
    command = [python, "-c", code]
    cleanup_path = None

    if sys.platform == "linux":
        if not sandbox.bwrap_available():
            raise RuntimeError(
                "bwrap (bubblewrap) is required for Linux PyRepl sandbox. "
                "Install with: apt-get install bubblewrap"
            )
        extra_binds = []
        if venv_root is not None:
            extra_binds.append(
                sandbox.BwrapBind(
                    source=str(venv_root),
                    target=_SANDBOX_VENV,
                    mode="readonly",
                )
            )
        command, cleanup_path = sandbox.build_bwrap_cmd(
            sandbox_root,
            command,
            workspace_uuid=workspace_uuid,
            extra_binds=extra_binds,
        )
    return command, cleanup_path


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    if _current_venv_root() is not None:
        env["VIRTUAL_ENV"] = _SANDBOX_VENV if sys.platform == "linux" else str(sys.prefix)
        bin_dir = (
            f"{_SANDBOX_VENV}/bin" if sys.platform == "linux" else str(Path(sys.prefix) / "bin")
        )
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    return env


async def pyrepl_handler(
    code: str,
    timeout_ms: int = 30000,
    *,
    ws=None,
    interrupt_event: asyncio.Event | None = None,
) -> ToolResult:
    """在独立子进程中运行 Python 代码。"""
    timeout_s = timeout_ms / 1000.0
    sandbox_root = str(getattr(ws, "root", Path.cwd()))
    workspace_uuid = getattr(ws, "uuid", None)

    proc = None
    try:
        command, cleanup_path = _build_command(
            code,
            sandbox_root=sandbox_root,
            workspace_uuid=workspace_uuid,
        )
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=sandbox_root,
            env=_build_env(),
            start_new_session=True,
        )

        communicate_task = asyncio.create_task(proc.communicate())
        wait_tasks = {communicate_task}

        interrupt_task = None
        if interrupt_event is not None:
            interrupt_task = asyncio.create_task(interrupt_event.wait())
            wait_tasks.add(interrupt_task)

        done, pending = await asyncio.wait(
            wait_tasks,
            timeout=timeout_s,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if interrupt_task is not None and interrupt_task in done:
            _kill_proc(proc)
            await proc.wait()
            communicate_task.cancel()
            return ToolResult(
                "[PyRepl interrupted]",
                status="interrupted",
                source="user",
                reason="interrupted_by_user",
            )

        if communicate_task not in done:
            _kill_proc(proc)
            await proc.wait()
            communicate_task.cancel()
            return ToolResult(
                f"[PyRepl timed out after {timeout_ms}ms]",
                status="timeout",
                source="tool",
                reason=f"timeout_ms={timeout_ms}",
            )

        if interrupt_task is not None:
            interrupt_task.cancel()
        for task in pending:
            task.cancel()

        stdout, _ = communicate_task.result()
        output = stdout.decode("utf-8", errors="replace") if stdout else ""

        if len(output) > _MAX_OUTPUT_BYTES:
            output = (
                output[:_MAX_OUTPUT_BYTES] + f"\n\n[Output truncated at {_MAX_OUTPUT_BYTES} bytes]"
            )
        return ToolResult(output if output.strip() else "(no output)")

    except Exception as exc:
        return ToolResult(
            f"PyRepl error: {exc}",
            status="error",
            source="tool",
            reason=str(exc),
        )
    finally:
        if cleanup_path := locals().get("cleanup_path"):
            with contextlib.suppress(OSError):
                Path(cleanup_path).rmdir()


def _kill_proc(proc) -> None:
    """Send SIGKILL to the subprocess process group."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        with contextlib.suppress(Exception):
            result = proc.kill()
            if inspect.isawaitable(result):
                result.close()


pyrepl_tool = StructuredTool.from_function(
    coroutine=pyrepl_handler,
    name="PyRepl",
    description="Run a snippet of Python code in a safe subprocess sandbox and return output.",
    args_schema=PyReplInput,
)
