"""Shadow repo commits, checkout, and task reconstruction."""

from __future__ import annotations

from typing import Any

from app.services.context import WorkspaceContext


class CheckpointService:
    def __init__(self, ctx: WorkspaceContext) -> None:
        self._ctx = ctx

    def list_commits(self, session_id: str) -> list[dict]:
        self._ctx.get_session(session_id)
        return self._ctx.shadow_repo.list_commits(session_id)

    def get_commit(self, session_id: str, sha: str) -> dict:
        self._ctx.get_session(session_id)
        return self._ctx.shadow_repo.get_commit(sha)

    async def checkout_session(self, session_id: str, req: Any) -> dict:
        session = self._ctx.get_session(session_id)
        if req.commit_sha:
            try:
                self._ctx.shadow_repo.restore(req.commit_sha)
            except KeyError:
                raise KeyError(f"Commit not found: {req.commit_sha}")
        user_content = ""
        if req.truncate_tid:
            user_content = session.find_user_question_content(req.truncate_tid)
        removed = session.truncate_transcripts_by_tid(
            req.truncate_tid or "", keep=req.keep_tid
        )
        await session.reconstruct_tasks()
        if req.commit_sha:
            try:
                self._ctx.shadow_repo.set_head(session_id, req.commit_sha)
            except Exception:
                pass
        return {
            "ok": True,
            "commit_sha": req.commit_sha,
            "removed": removed,
            "user_content": user_content,
        }
