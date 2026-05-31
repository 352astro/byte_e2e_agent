"""Workspace query and switching."""

from __future__ import annotations

from app.services.context import WorkspaceContext
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

        workspaces = list_workspaces()
        current = self._ctx.workspace
        if current not in workspaces:
            workspaces = [current, *workspaces]
        return workspaces

    def resolve_workspace(self, path: str | None = None) -> str:
        return self._ctx.resolve_workspace(path)
