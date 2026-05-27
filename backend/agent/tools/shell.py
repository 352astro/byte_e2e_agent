"""Shell 工具 — 委托 Sandbox 执行。"""

import sys

from pydantic import Field

from agent.tools.base import BaseTool

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


class Shell(BaseTool):
    """在持久 shell 中执行单行命令。"""

    timeout_ms: int = Field(
        default=30000,
        ge=1000,
        le=120000,
        description="Timeout in milliseconds.",
    )
    command: str = Field(
        ...,
        description="Single-line shell command.",
    )

    async def execute(self, sandbox=None) -> str:
        return await sandbox.run_shell(self.command, self.timeout_ms)
