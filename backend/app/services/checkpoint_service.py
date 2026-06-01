"""Shadow repo commits and workspace/message rewind operations."""

from __future__ import annotations

from app.services.context import WorkspaceContext
from app.services.errors import CommitNotFound, SessionNotFound
from app.services.session_scope import SessionLocator


class CheckpointService:
    def __init__(self, ctx: WorkspaceContext) -> None:
        self._ctx = ctx
        self._locator = SessionLocator(ctx)

    def _scoped_context(self, session_id: str) -> WorkspaceContext:
        scope = self._locator.resolve(session_id)
        return self._ctx.scoped(scope.workspace)

    def list_commits(self, session_id: str) -> list[dict]:
        try:
            ctx = self._scoped_context(session_id)
            ctx.get_session(session_id)
        except (KeyError, SessionNotFound) as exc:
            raise SessionNotFound(session_id) from exc
        return ctx.shadow_repo.list_commits(session_id)

    def get_commit(self, session_id: str, sha: str) -> dict:
        try:
            ctx = self._scoped_context(session_id)
            ctx.get_session(session_id)
        except (KeyError, SessionNotFound) as exc:
            raise SessionNotFound(session_id) from exc
        try:
            return ctx.shadow_repo.get_commit(sha)
        except KeyError as exc:
            raise CommitNotFound(sha) from exc

    def restore_workspace(
        self, session_id: str, commit_sha: str, *, set_head: bool = True
    ) -> dict:
        try:
            ctx = self._scoped_context(session_id)
            ctx.get_session(session_id)
        except (KeyError, SessionNotFound) as exc:
            raise SessionNotFound(session_id) from exc
        try:
            ctx.shadow_repo.restore(commit_sha)
        except KeyError as exc:
            raise CommitNotFound(commit_sha) from exc
        if set_head:
            ctx.shadow_repo.set_head(session_id, commit_sha)
        return {"ok": True, "commit_sha": commit_sha}

    def truncate_messages(
        self, session_id: str, message_id: str, *, keep: bool = False
    ) -> dict:
        try:
            ctx = self._scoped_context(session_id)
            session = ctx.get_session(session_id)
        except (KeyError, SessionNotFound) as exc:
            raise SessionNotFound(session_id) from exc
        removed = session.truncate_by_id(message_id, keep=keep)
        return {
            "ok": True,
            "message_id": message_id,
            "removed": removed,
        }
