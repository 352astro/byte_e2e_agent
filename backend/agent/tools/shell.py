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

    async def execute(
        self,
        *,
        sandbox=None,
        channel=None,
        interrupt_event=None,
        scheduler=None,
        toolset=None,
        result_id: str = "",
    ) -> str:
        """流式执行 Shell。结果已 chunk 到 channel，
        返回空字符串表示调用方无需再 chunk。"""
        rid = result_id
        async for chunk_text in sandbox.stream_shell(
            self.command,
            self.timeout_ms,
            interrupt_event=interrupt_event,
        ):
            if channel is not None:
                await channel.chunk(rid, "tool_result", chunk_text, chunk_id=rid)
        exit_code = sandbox.terminal._last_exit_code
        if exit_code not in (0, -1) and channel is not None:
            await channel.chunk(
                rid, "tool_result", f"\n[exit code: {exit_code}]", chunk_id=rid
            )
        return ""
