"""Resolve a session id to its owning workspace and storage paths."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.core.workspace import Workspace as CoreWorkspace
from app.services.context import WorkspaceContext
from app.services.errors import AmbiguousSession, SessionNotFound
from app.services.workspace_registry import list_workspaces, register_workspace

SESSION_META_FILE = "session.json"


@dataclass(frozen=True)
class SessionScope:
    session_id: str
    workspace: str
    session_dir: Path
    messages_path: Path
    config_path: Path
    metadata_path: Path


class SessionLocator:
    def __init__(self, ctx: WorkspaceContext) -> None:
        self._ctx = ctx

    def resolve(
        self,
        session_id: str,
        *,
        workspace_hint: str | None = None,
    ) -> SessionScope:
        candidates = self._candidate_workspaces(workspace_hint)
        matches = [
            scope
            for scope in (
                self._scope_if_exists(workspace, session_id)
                for workspace in candidates
            )
            if scope is not None
        ]
        if not matches:
            raise SessionNotFound(session_id)
        if len(matches) > 1:
            raise AmbiguousSession(session_id, [scope.workspace for scope in matches])
        return matches[0]

    def _candidate_workspaces(self, workspace_hint: str | None) -> list[str]:
        raw = [workspace_hint, self._ctx.workspace, *list_workspaces().values()]
        result: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not item:
                continue
            try:
                resolved = self._ctx.resolve_workspace(item)
            except ValueError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            result.append(resolved)
        return result

    @staticmethod
    def _scope_if_exists(workspace: str, session_id: str) -> SessionScope | None:
        try:
            resolved_workspace, workspace_uuid = register_workspace(workspace)
        except ValueError:
            return None
        core = CoreWorkspace(resolved_workspace, workspace_uuid=workspace_uuid)
        try:
            session_dir = core.session_dir(session_id)
        except ValueError:
            return None
        messages_path = session_dir / "messages.jsonl"
        if not messages_path.is_file():
            return None
        return SessionScope(
            session_id=session_id,
            workspace=resolved_workspace,
            session_dir=session_dir,
            messages_path=messages_path,
            config_path=session_dir / "config.json",
            metadata_path=session_dir / SESSION_META_FILE,
        )


def read_session_metadata(scope: SessionScope) -> dict[str, Any]:
    if not scope.metadata_path.is_file():
        return {}
    try:
        data = json.loads(scope.metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def write_session_metadata(scope: SessionScope) -> None:
    now = datetime.now(UTC).isoformat()
    existing = read_session_metadata(scope)
    payload = {
        **existing,
        "session_id": scope.session_id,
        "workspace": scope.workspace,
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
    }
    scope.metadata_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
