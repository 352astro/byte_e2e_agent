"""ListDir tool — safe, compact directory listing inside the workspace."""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class ListDirInput(BaseModel):
    """ListDir tool input parameters."""

    path: str = Field(
        default=".",
        description="Directory path relative to the workspace root.",
    )
    recursive: bool = Field(
        default=False,
        description="Whether to recursively list subdirectories.",
    )
    max_depth: int = Field(
        default=2,
        ge=1,
        le=8,
        description="Maximum recursion depth when recursive is true.",
    )
    max_entries: int = Field(
        default=200,
        ge=1,
        le=2000,
        description="Maximum number of entries to return.",
    )
    include_hidden: bool = Field(
        default=False,
        description="Include dotfiles and dot-directories.",
    )


async def listdir_handler(
    path: str = ".",
    recursive: bool = False,
    max_depth: int = 2,
    max_entries: int = 200,
    include_hidden: bool = False,
    *,
    workspace=None,
) -> str:
    """List files and directories under a workspace directory."""
    workspace_obj = workspace
    try:
        root = Path(workspace_obj.resolve_path("."))
        target = workspace_obj.resolve(path, external_mode="readonly")
    except PermissionError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Error: invalid path '{path}': {exc}"

    if not target.exists():
        return f"Error: directory not found '{path}'"
    if not target.is_dir():
        return f"Error: '{path}' is not a directory"

    try:
        display_path = str(target.relative_to(root)) if target != root else "."
    except ValueError:
        display_path = str(target)
    lines: list[str] = [f"{display_path}/"]
    count = 0
    truncated = False

    def visible(entry: Path) -> bool:
        return include_hidden or not entry.name.startswith(".")

    def sort_key(entry: Path) -> tuple[int, str]:
        return (0 if entry.is_dir() else 1, entry.name.lower())

    def walk(directory: Path, depth: int) -> None:
        nonlocal count, truncated
        if truncated:
            return
        try:
            entries = sorted(
                (entry for entry in directory.iterdir() if visible(entry)),
                key=sort_key,
            )
        except OSError as exc:
            indent = "  " * depth
            lines.append(f"{indent}[error reading directory: {exc}]")
            return

        for entry in entries:
            if count >= max_entries:
                truncated = True
                return
            count += 1
            suffix = "/" if entry.is_dir() else ""
            indent = "  " * depth
            lines.append(f"{indent}{entry.name}{suffix}")
            if recursive and entry.is_dir() and depth < max_depth:
                walk(entry, depth + 1)
                if truncated:
                    return

    walk(target, 1)

    if count == 0:
        lines.append("  (empty)")
    if truncated:
        lines.append(f"... truncated after {max_entries} entries")

    return "\n".join(lines)


listdir_tool = StructuredTool.from_function(
    coroutine=listdir_handler,
    name="ListDir",
    description=(
        "List files and directories in the workspace. Prefer this over Shell "
        "for directory exploration."
    ),
    args_schema=ListDirInput,
)
