"""Glob 工具 — 按模式匹配文件路径。"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class GlobInput(BaseModel):
    """Glob 工具输入参数。"""

    pattern: str = Field(
        ...,
        description=(
            "Glob pattern (e.g. '**/*.py', 'src/**/*.ts'). "
            "Hint: avoid scanning the agent session storage directory — it contains "
            "session metadata and is not part of the user's codebase."
        ),
    )
    max_results: int = Field(
        default=200,
        ge=1,
        le=1000,
        description="Maximum number of results to return.",
    )


async def glob_handler(pattern: str, max_results: int = 200, *, ws) -> str:
    """Find files matching a glob pattern and return sorted relative paths."""
    try:
        workspace = Path(ws.resolve_path("."))
    except Exception:
        workspace = Path(".")

    try:
        matches = sorted(
            str(p.relative_to(workspace)) for p in workspace.rglob(pattern)
        )
    except Exception as exc:
        return f"Error: invalid glob pattern '{pattern}': {exc}"

    if not matches:
        return f"No files matching '{pattern}'."

    total = len(matches)
    matches = matches[:max_results]

    lines = [f"{len(matches)} of {total} matches for '{pattern}':"]
    lines.extend(f"  {m}" for m in matches)
    if total > max_results:
        lines.append(f"  ... ({total - max_results} more)")

    return "\n".join(lines)


glob_tool = StructuredTool.from_function(
    coroutine=glob_handler,
    name="Glob",
    description="Find files matching a glob pattern and return sorted relative paths.",
    args_schema=GlobInput,
)
