"""Grep 工具 — 正则搜索文件内容（流式 + 可中断）。"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import Field

from agent.tools.base import BaseTool

# — 单文件最大读取 —
_MAX_FILE_BYTES = 1_048_576  # 1 MiB


def _is_binary(path: Path) -> bool:
    """Try decoding the first 4 KB; if it fails, treat as binary."""
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(4096)
        chunk.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


def _read_lines(path: Path) -> list[str] | None:
    """Read lines from a text file.  Returns None for binary / oversized."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()
    except Exception:
        return None


class Grep(BaseTool):
    """Search file contents with a regex pattern and return matching lines.
    Results are streamed to the frontend as they are found."""

    regex: str = Field(
        ..., description="Regex pattern to search for (Python re syntax)."
    )
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
        try:
            workspace = Path(sandbox.resolve_path("."))
        except Exception:
            workspace = Path(".")

        try:
            compiled = re.compile(self.regex)
        except re.error as exc:
            return f"Error: invalid regex '{self.regex}': {exc}"

        match_count = 0
        files_scanned = 0
        results: list[str] = []

        for p in workspace.rglob(self.include_pattern):
            # ── 中断检查 ──────────────────────────
            if interrupt_event is not None and interrupt_event.is_set():
                msg = "\n[Search interrupted by user]"
                if channel is not None:
                    await channel.chunk(
                        result_id, "tool_result", msg, chunk_id=result_id
                    )
                else:
                    results.append(msg)
                break

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
                    text = f"{rel}:{lineno}: {line}"
                    if channel is not None:
                        await channel.chunk(
                            result_id,
                            "tool_result",
                            text + "\n",
                            chunk_id=result_id,
                        )
                    else:
                        results.append(text)
                    if match_count >= self.max_results:
                        break
            if match_count >= self.max_results:
                break

        # ── 摘要 ──────────────────────────────────
        if match_count == 0:
            return f"No matches for '{self.regex}' (scanned {files_scanned} files)."

        summary = (
            f"\n{match_count} match(es) for '{self.regex}' in {files_scanned} file(s)."
        )
        if channel is not None:
            await channel.chunk(result_id, "tool_result", summary, chunk_id=result_id)
            return ""
        results.append(summary)
        return "\n".join(results)
