"""Grep 工具 — 正则搜索文件内容。"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

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


def _truncate(text: str, max_bytes: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    truncated = raw[:max_bytes].decode("utf-8", errors="replace")
    return (
        f"{truncated}\n[... truncated at {max_bytes} bytes, {len(raw) - max_bytes} bytes omitted]"
    )


class GrepInput(BaseModel):
    """Grep 工具输入参数。"""

    include_pattern: str = Field(
        default="**/*",
        description=(
            "Glob to filter which files to search (e.g. '**/*.py'). "
            "Hint: exclude the agent session storage directory to avoid scanning metadata."
        ),
    )
    max_results: int = Field(
        default=200,
        ge=1,
        le=1000,
        description="Maximum number of matching lines to return.",
    )
    max_bytes: int = Field(
        default=50_000,
        ge=1000,
        le=500_000,
        description="Maximum UTF-8 bytes to return before truncating.",
    )
    regex: str = Field(..., description="Regex pattern to search for (Python re syntax).")


async def grep_handler(
    regex: str,
    include_pattern: str = "**/*",
    max_results: int = 200,
    max_bytes: int = 50_000,
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

    footer = f"\n{match_count} match(es) for '{regex}' in {files_scanned} file(s)."
    body = "\n".join(results)
    return _truncate(body, max_bytes) + footer


grep_tool = StructuredTool.from_function(
    coroutine=grep_handler,
    name="Grep",
    description="Search file contents with a regex pattern and return matching lines.",
    args_schema=GrepInput,
)
