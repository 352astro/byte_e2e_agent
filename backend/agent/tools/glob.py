"""Glob 工具 — 按模式匹配文件路径。"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from agent.tools.base import BaseTool


class Glob(BaseTool):
    """Find files matching a glob pattern and return sorted relative paths."""

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

    async def execute(
        self,
        *,
        sandbox=None,
        channel=None,
        interrupt_event=None,
        scheduler=None,
        toolset=None,
        result_id="",
    ) -> str:
        try:
            workspace = Path(sandbox.resolve_path("."))
        except Exception:
            workspace = Path(".")

        try:
            matches = sorted(
                str(p.relative_to(workspace)) for p in workspace.rglob(self.pattern)
            )
        except Exception as exc:
            return f"Error: invalid glob pattern '{self.pattern}': {exc}"

        if not matches:
            return f"No files matching '{self.pattern}'."

        total = len(matches)
        matches = matches[: self.max_results]

        lines = [f"{len(matches)} of {total} matches for '{self.pattern}':"]
        lines.extend(f"  {m}" for m in matches)
        if total > self.max_results:
            lines.append(f"  ... ({total - self.max_results} more)")

        return "\n".join(lines)
