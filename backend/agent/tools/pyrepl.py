"""PyRepl 工具 — 安全受限的 Python 子进程执行器。

通过独立子进程执行用户代码，避免:
- exec() 阻塞事件循环
- 恶意代码影响主进程
- 中断无法生效

安全模型: 子进程以 -S 启动（禁用 site），通过受限 builtins 执行。
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import textwrap

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

_MAX_OUTPUT_BYTES = 10_240  # 10 KiB
_DEFAULT_TIMEOUT_S = 30


class PyReplInput(BaseModel):
    """PyRepl 工具输入参数。"""

    code: str = Field(
        ...,
        description=(
            "Python code to execute. The sandbox exposes print() and basic "
            "builtins (int, str, list, dict, sorted, zip, ...). I/O and "
            "imports are blocked."
        ),
    )
    timeout_ms: int = Field(
        default=30000,
        ge=1000,
        le=60000,
        description="Timeout in milliseconds.",
    )


def _build_sandbox_script(code: str) -> str:
    """构建受限执行脚本，通过 restricted builtins 运行用户代码。"""
    # 安全白名单内置函数
    safe_names = [
        "print",
        "len",
        "range",
        "int",
        "float",
        "str",
        "bool",
        "bytes",
        "list",
        "dict",
        "set",
        "tuple",
        "frozenset",
        "enumerate",
        "zip",
        "map",
        "filter",
        "sorted",
        "reversed",
        "iter",
        "next",
        "slice",
        "abs",
        "min",
        "max",
        "sum",
        "round",
        "pow",
        "divmod",
        "ord",
        "chr",
        "repr",
        "hash",
        "id",
        "type",
        "isinstance",
        "issubclass",
        "callable",
        "hasattr",
        "all",
        "any",
        "Exception",
        "ValueError",
        "TypeError",
        "KeyError",
        "IndexError",
        "StopIteration",
        "True",
        "False",
        "None",
    ]
    safe_builtins = ",\n        ".join(
        f'"{n}": __builtins__["{n}"]' for n in safe_names
    )

    return textwrap.dedent(f"""\
    import builtins as __builtins__
    __safe = {{
        {safe_builtins}
    }}
    __builtins__["__import__"] = __import__

    try:
        exec({code!r}, {{"__builtins__": __safe}})
    except SystemExit:
        pass
    """)


async def pyrepl_handler(
    code: str,
    timeout_ms: int = 30000,
    *,
    ws=None,
    interrupt_event: asyncio.Event | None = None,
) -> str:
    """在独立子进程中运行 Python 代码。"""
    script = _build_sandbox_script(code)
    timeout_s = timeout_ms / 1000.0

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-S",  # 禁用 site-packages
            "-c",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
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
            return "[PyRepl interrupted]"

        if communicate_task not in done:
            _kill_proc(proc)
            await proc.wait()
            communicate_task.cancel()
            return f"[PyRepl timed out after {timeout_ms}ms]"

        if interrupt_task is not None:
            interrupt_task.cancel()
        for task in pending:
            task.cancel()

        stdout, _ = communicate_task.result()
        output = stdout.decode("utf-8", errors="replace") if stdout else ""

        if len(output) > _MAX_OUTPUT_BYTES:
            output = (
                output[:_MAX_OUTPUT_BYTES]
                + f"\n\n[Output truncated at {_MAX_OUTPUT_BYTES} bytes]"
            )
        return output if output.strip() else "(no output)"

    except Exception as exc:
        return f"PyRepl error: {exc}"


def _kill_proc(proc) -> None:
    """Send SIGKILL to the subprocess.

    Uses os.kill (single process), NOT os.killpg (entire process group).
    killpg is dangerous: if the child process exits and its PID is reused
    by the kernel for a process-group-leader (e.g. a shell session),
    killpg would kill that entire group, causing unexpected logout.
    """
    try:
        os.kill(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


pyrepl_tool = StructuredTool.from_function(
    coroutine=pyrepl_handler,
    name="PyRepl",
    description="Run a snippet of Python code in a safe subprocess sandbox and return output.",
    args_schema=PyReplInput,
)
