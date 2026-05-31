"""Workspace query and switching."""

from __future__ import annotations

from app.services.context import WorkspaceContext


class WorkspaceService:
    def __init__(self, ctx: WorkspaceContext) -> None:
        self._ctx = ctx

    def get_workspace(self) -> str:
        return self._ctx.workspace

    def set_workspace(self, path: str) -> None:
        self._ctx.set_workspace(path)

    def resolve_workspace(self, path: str | None = None) -> str:
        return self._ctx.resolve_workspace(path)
