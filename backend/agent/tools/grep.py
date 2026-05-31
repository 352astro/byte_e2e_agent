"""Grep 工具 — 正则搜索文件内容。"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.core.config import TMP_DIR

_MAX_FILE_BYTES = 1_048_576  # 1 MiB


def _is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(4096)
        chunk.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


def _read_lines(path: Path) -> list[str] | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()
    except Exception:
        return None


class GrepInput(BaseModel):
    """Grep 工具输入参数。"""

    regex: str = Field(
        ..., description="Regex pattern to search for (Python re syntax)."
    )
    include_pattern: str = Field(
        default="**/*",
        description=(
            "Glob to filter which files to search (e.g. '**/*.py'). "
            "Hint: exclude " + TMP_DIR + "/ to avoid scanning session metadata."
        ),
    )
    max_results: int = Field(
        default=200,
        ge=1,
        le=1000,
        description="Maximum number of matching lines to return.",
    )


async def grep_handler(
    regex: str,
    include_pattern: str = "**/*",
    max_results: int = 200,
    *,
    ws,
) -> str:
    """Search file contents with a regex pattern and return matching lines."""
    try:
        workspace = Path(ws.resolve_path("."))
    except Exception:
        workspace = Path(".")

    try:
        compiled = re.compile(regex)
    except re.error as exc:
        return f"Error: invalid regex '{regex}': {exc}"

    match_count = 0
    files_scanned = 0
    results: list[str] = []

    for p in workspace.rglob(include_pattern):
        if not p.is_file():
            continue
        if _is_binary(p):
            continue
        files_scanned += 1

        lines = _read_lines(p)
        if lines is None:
            continue

        rel = str(p.relative_to(workspace))
        for lineno, line in enumerate(lines, 1):
            if compiled.search(line):
                match_count += 1
                results.append(f"{rel}:{lineno}: {line}")
                if match_count >= max_results:
                    break
        if match_count >= max_results:
            break

    if match_count == 0:
        return f"No matches for '{regex}' (scanned {files_scanned} files)."

    results.append(
        f"\n{match_count} match(es) for '{regex}' in {files_scanned} file(s)."
    )
    return "\n".join(results)


grep_tool = StructuredTool.from_function(
    coroutine=grep_handler,
    name="Grep",
    description="Search file contents with a regex pattern and return matching lines.",
    args_schema=GrepInput,
)
