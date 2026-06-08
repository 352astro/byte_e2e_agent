"""Read 工具 — 读取 workspace 文件。"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class ReadInput(BaseModel):
    """Read 工具输入参数。"""

    start_line: int = Field(default=1, ge=1, description="First line to read (1-based).")
    end_line: int = Field(
        default=0,
        ge=0,
        description="Last line to read (1-based, inclusive). 0 = read to end of file.",
    )
    max_bytes: int = Field(
        default=50_000,
        ge=1000,
        le=500_000,
        description="Maximum UTF-8 bytes to return before truncating.",
    )
    path: str = Field(..., description="File path to read (relative to workspace).")


def _truncate(text: str, max_bytes: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    truncated = raw[:max_bytes].decode("utf-8", errors="replace")
    return (
        f"{truncated}\n[... truncated at {max_bytes} bytes, {len(raw) - max_bytes} bytes omitted]"
    )


async def read_handler(
    path: str,
    start_line: int = 1,
    end_line: int = 0,
    max_bytes: int = 50_000,
    *,
    workspace=None,
) -> str:
    """Read a file (or a line range) from the workspace."""
    full = await workspace.read_file(path)
    if full.startswith("Error:"):
        return full
    if full == "(empty)":
        return full

    lines = full.splitlines()
    total = len(lines)

    start = max(1, start_line) - 1  # 0-based
    end = end_line if end_line > 0 else total
    end = min(end, total)

    if start >= total:
        return f"Error: start_line {start_line} exceeds file length ({total} lines)."

    sliced = lines[start:end]
    result = "\n".join(sliced)

    if start > 0 or end < total:
        result = f"[lines {start + 1}-{end} of {total}]\n" + result

    result = result if result else "(empty)"
    return _truncate(result, max_bytes)


read_tool = StructuredTool.from_function(
    coroutine=read_handler,
    name="Read",
    description="Read a file (or a line range) from the workspace.",
    args_schema=ReadInput,
)
