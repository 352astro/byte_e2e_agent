"""
Bash 工具：在受限环境中执行 shell 命令。
"""

import subprocess
from typing import Literal

from pydantic import Field

from agent.tools._safety import check_command_safety
from agent.tools.base import BaseTool
from agent.tools.workspace import get_workspace_root


class Bash(BaseTool):
    """
    执行单行 shell 命令并返回输出。

    危险指令（sudo / rm -rf / / mkfs 等）会被自动拦截。
    命令在工作目录下执行，超时默认 30 秒。
    """

    kind: Literal["Bash"] = "Bash"

    command: str = Field(
        ...,
        description="Single-line shell command to execute. E.g. 'ls -la' or 'cat file.txt'",
    )
    timeout_ms: int = Field(
        default=30000,
        ge=1000,
        le=120000,
        description="Timeout in milliseconds (default 30000 = 30 s, max 120000 = 2 min)",
    )

    def execute(self) -> str:
        """执行 shell 命令并返回 stdout/stderr 拼接结果。"""
        # 1. 安全检查
        try:
            check_command_safety(self.command)
        except ValueError as exc:
            return f"Error: {exc}"

        root = get_workspace_root()

        try:
            result = subprocess.run(
                self.command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=root,
                timeout=self.timeout_ms / 1000.0,
            )

            parts: list[str] = []

            if result.stdout:
                parts.append(result.stdout.rstrip())
            if result.stderr:
                parts.append(f"[stderr]\n{result.stderr.rstrip()}")

            if result.returncode != 0:
                parts.append(f"[exit code: {result.returncode}]")

            return "\n".join(parts) if parts else "(no output)"

        except subprocess.TimeoutExpired:
            return f"Error: command timed out ({self.timeout_ms} ms)"
        except FileNotFoundError:
            return f"Error: command not found '{self.command.split()[0] if self.command.strip() else ''}'"
        except Exception as exc:
            return f"Error: {exc}"
