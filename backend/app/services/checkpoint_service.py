"""Shadow repo commits and workspace/message rewind operations."""

from __future__ import annotations

from app.services.context import WorkspaceContext
from app.services.errors import CommitNotFound, SessionNotFound


class CheckpointService:
    def __init__(self, ctx: WorkspaceContext) -> None:
        self._ctx = ctx

    def list_commits(self, session_id: str) -> list[dict]:
        try:
            self._ctx.get_session(session_id)
        except KeyError as exc:
            raise SessionNotFound(session_id) from exc
        return self._ctx.shadow_repo.list_commits(session_id)

    def get_commit(self, session_id: str, sha: str) -> dict:
        try:
            self._ctx.get_session(session_id)
            return self._ctx.shadow_repo.get_commit(sha)
        except KeyError as exc:
            raise CommitNotFound(sha) from exc

    def restore_workspace(
        self, session_id: str, commit_sha: str, *, set_head: bool = True
    ) -> dict:
        try:
            self._ctx.get_session(session_id)
        except KeyError as exc:
            raise SessionNotFound(session_id) from exc
        try:
            self._ctx.shadow_repo.restore(commit_sha)
        except KeyError as exc:
            raise CommitNotFound(commit_sha) from exc
        if set_head:
            self._ctx.shadow_repo.set_head(session_id, commit_sha)
        return {"ok": True, "commit_sha": commit_sha}

    def truncate_messages(
        self, session_id: str, message_id: str, *, keep: bool = False
    ) -> dict:
        try:
            session = self._ctx.get_session(session_id)
        except KeyError as exc:
            raise SessionNotFound(session_id) from exc
        removed = session.truncate_by_id(message_id, keep=keep)
        return {
            "ok": True,
            "message_id": message_id,
            "removed": removed,
        }
