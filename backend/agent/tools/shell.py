"""
Shell 工具：在持久 shell 会话中执行命令。

委托给 PersistentTerminal 实例，支持 cd / export 等有状态操作。
自动适配平台：Linux/macOS 使用 bash，Windows 使用 cmd.exe。
"""

import sys
from typing import Literal

from pydantic import Field

from agent.terminal import TerminalResult, get_terminal
from agent.tools._safety import check_command_safety
from agent.tools.base import BaseTool

# ── 平台描述（注入 System Prompt） ────────────────────

_PLATFORM_MAP = {
    "linux": "Linux",
    "darwin": "macOS",
    "win32": "Windows",
}


def get_platform_hint() -> str:
    """返回一段提示 LLM 当前平台的文字。"""
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


# ── Shell 工具 ────────────────────────────────────────


class Shell(BaseTool):
    """
    在持久 shell 中执行单行命令并返回输出。

    危险指令（sudo / rm -rf / / mkfs 等）会被自动拦截。
    命令在工作目录下执行，超时默认 30 秒。
    平台自适应：Linux/macOS → bash, Windows → cmd.exe。
    """

    kind: Literal["Shell"] = "Shell"

    command: str = Field(
        ...,
        description="Single-line shell command. Use Unix syntax on Linux/macOS, cmd syntax on Windows.",
    )
    timeout_ms: int = Field(
        default=30000,
        ge=1000,
        le=120000,
        description="Timeout in milliseconds (default 30000 = 30 s, max 120000 = 2 min)",
    )

    def execute(self) -> str:
        """在持久终端中执行命令，返回格式化的输出字符串。"""
        try:
            check_command_safety(self.command)
        except ValueError as exc:
            return f"Error: {exc}"

        try:
            terminal = get_terminal()
        except RuntimeError:
            return (
                "Error: PersistentTerminal not available. "
                "The agent runtime must initialise a terminal first."
            )

        try:
            result: TerminalResult = terminal.run(self.command, self.timeout_ms)
        except Exception as exc:
            return f"Error: {exc}"

        parts: list[str] = []
        if result.output.strip():
            parts.append(result.output.rstrip())
        if result.exit_code != 0:
            parts.append(f"[exit code: {result.exit_code}]")
        return "\n".join(parts) if parts else "(no output)"
