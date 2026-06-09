"""Workspace query and switching."""

from __future__ import annotations

import os
from pathlib import Path

from app.services.workspace_context import WorkspaceContext
from app.services.workspace_registry import register_workspace


class WorkspaceService:
    def __init__(self, ctx: WorkspaceContext) -> None:
        self._ctx = ctx

    def get_workspace(self) -> str:
        return self._ctx.workspace

    def set_workspace(self, path: str) -> None:
        self._ctx.set_workspace(path)
        register_workspace(self._ctx.workspace)

    def list_registered_workspaces(self) -> list[str]:
        from app.services.workspace_registry import list_workspaces

        mapping = list_workspaces()
        paths = list(mapping.values())
        current = self._ctx.workspace
        if current not in paths:
            paths = [current, *paths]
        return paths

    def resolve_workspace(self, path: str | None = None) -> str:
        return self._ctx.resolve_workspace(path)

    def resolve_file(self, path: str) -> Path:
        if not path or not path.strip():
            raise ValueError("path is required")
        resolved = self._ctx.core_workspace.resolve(path.strip())
        if resolved.is_dir():
            raise ValueError("path points to a directory")
        return resolved

    def get_picker_context(self) -> dict:
        return {
            "workspace": self._ctx.workspace,
            "home": str(Path.home()),
            "roots": self._list_roots(),
        }

    def list_directory(
        self,
        path: str | None = None,
        *,
        show_hidden: bool = False,
    ) -> dict:
        target = self._resolve_picker_path(path)
        if not target.exists():
            raise ValueError("path does not exist")
        if not target.is_dir():
            raise ValueError("path is not a directory")
        if not os.access(target, os.R_OK | os.X_OK):
            raise PermissionError(f"Cannot read directory: {target}")

        entries = []
        try:
            children = list(target.iterdir())
        except PermissionError:
            raise
        except OSError as exc:
            raise ValueError(str(exc)) from exc

        for child in children:
            name = child.name
            hidden = name.startswith(".")
            if hidden and not show_hidden:
                continue

            try:
                stat = child.stat(follow_symlinks=False)
            except OSError:
                stat = None

            try:
                is_dir = child.is_dir()
                is_file = child.is_file()
            except OSError:
                is_dir = False
                is_file = False

            if is_dir:
                kind = "directory"
                readable = os.access(child, os.R_OK | os.X_OK)
                size = None
            elif is_file:
                kind = "file"
                readable = os.access(child, os.R_OK)
                size = stat.st_size if stat else None
            else:
                kind = "other"
                readable = os.access(child, os.R_OK)
                size = stat.st_size if stat else None

            entries.append(
                {
                    "name": name,
                    "path": str(child),
                    "kind": kind,
                    "hidden": hidden,
                    "readable": readable,
                    "size": size,
                    "modified_at": stat.st_mtime if stat else None,
                }
            )

        entries.sort(
            key=lambda item: (
                0 if item["kind"] == "directory" else 1,
                item["name"].lower(),
            )
        )
        parent = None if target.parent == target else str(target.parent)
        return {
            "path": str(target),
            "parent": parent,
            "home": str(Path.home()),
            "roots": self._list_roots(),
            "entries": entries,
        }

    def _resolve_picker_path(self, path: str | None) -> Path:
        if path is None or not path.strip():
            return Path(self._ctx.workspace).resolve()

        raw = Path(path.strip()).expanduser()
        if raw.is_absolute():
            return raw.resolve()
        return (Path(self._ctx.workspace) / raw).resolve()

    def _list_roots(self) -> list[str]:
        if os.name == "nt":
            roots = []
            for code in range(ord("A"), ord("Z") + 1):
                root = f"{chr(code)}:\\"
                if Path(root).exists():
                    roots.append(root)
            return roots
        return ["/"]
