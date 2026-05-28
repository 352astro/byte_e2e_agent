"""Read 工具 — 委托 Sandbox 读取文件。"""

from __future__ import annotations

from pydantic import Field

from agent.tools.base import BaseTool


class Read(BaseTool):
    """Read a file (or a line range) from the workspace."""

    path: str = Field(
        ...,
        description="File path to read (relative to workspace).",
    )
    start_line: int = Field(
        default=1,
        ge=1,
        description="First line to read (1-based).",
    )
    end_line: int = Field(
        default=0,
        ge=0,
        description=(
            "Last line to read (1-based, inclusive). 0 = read to end of file."
        ),
    )

    async def execute(self, *, sandbox=None, channel=None, interrupt_event=None, scheduler=None, toolset=None, result_id="") -> str:
        full = await sandbox.read_file(self.path)
        # 错误信息直接返回
        if full.startswith("Error:"):
            return full
        if full == "(empty)":
            return full

        lines = full.splitlines()
        total = len(lines)

        start = max(1, self.start_line) - 1  # 0-based
        end = self.end_line if self.end_line > 0 else total
        end = min(end, total)

        if start >= total:
            return (
                f"Error: start_line {self.start_line} exceeds "
                f"file length ({total} lines)."
            )

        sliced = lines[start:end]
        result = "\n".join(sliced)

        if start > 0 or end < total:
            result = f"[lines {start + 1}-{end} of {total}]\n" + result
        return result if result else "(empty)"
