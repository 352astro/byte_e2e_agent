"""Shell 工具 — 委托 Workspace 执行。"""

import sys

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

_PLATFORM_MAP = {"linux": "Linux", "darwin": "macOS", "win32": "Windows"}


def get_platform_hint() -> str:
    name = _PLATFORM_MAP.get(sys.platform, sys.platform)
    if sys.platform == "win32":
        return (
            f"Current platform: {name}. "
            "Use cmd.exe commands (dir, type, echo %VAR%, etc.). "
            "Avoid bash-specific syntax (ls, cat, $VAR)."
        )
    else:
        return (
            f"Current platform: {name}. "
            "Use Unix shell commands (ls, cat, grep, $VAR, etc.). "
            "Avoid cmd.exe / PowerShell syntax."
        )


class ShellInput(BaseModel):
    """Shell 工具输入参数。"""

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
    """在 workspace 中执行 shell 命令。"""
    return await ws.run_shell(command, timeout_ms, interrupt_event=interrupt_event)


shell_tool = StructuredTool.from_function(
    coroutine=shell_handler,
    name="Shell",
    description="Execute a single-line shell command in the workspace.",
    args_schema=ShellInput,
)
