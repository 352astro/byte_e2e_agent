"""Shadow repo commits and workspace/message rewind operations."""

from __future__ import annotations

import re

from app.services.errors import CommitNotFound, SessionNotFound
from app.services.session_scope import SessionLocator
from app.services.session_service import SessionService
from app.services.workspace_context import WorkspaceContext

_SUBAGENT_RESULT_RE = re.compile(r"SubAgent session ([A-Za-z0-9_-]+) completed")


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
            ctx.get_info(session_id)
        except (KeyError, SessionNotFound) as exc:
            raise SessionNotFound(session_id) from exc
        return ctx.shadow_repo.list_commits(session_id)

    def get_commit(self, session_id: str, sha: str) -> dict:
        try:
            ctx = self._scoped_context(session_id)
            ctx.get_info(session_id)
        except (KeyError, SessionNotFound) as exc:
            raise SessionNotFound(session_id) from exc
        try:
            return ctx.shadow_repo.get_commit(sha)
        except KeyError as exc:
            raise CommitNotFound(sha) from exc

    def restore_workspace(self, session_id: str, commit_sha: str, *, set_head: bool = True) -> dict:
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

    async def truncate_messages(
        self, session_id: str, message_id: str, *, keep: bool = False
    ) -> dict:
        try:
            ctx = self._scoped_context(session_id)
            session = ctx.get_session(session_id)
        except (KeyError, SessionNotFound) as exc:
            raise SessionNotFound(session_id) from exc
        messages = session.get_messages()
        removed_messages = _messages_removed_by_truncate(messages, message_id, keep=keep)
        removed_message_ids = {
            msg_id
            for msg in removed_messages
            if isinstance((msg_id := msg.get("id")), str) and msg_id
        }
        removed = session.truncate_by_id(message_id, keep=keep)
        session_service = SessionService(self._ctx)
        deleted_subagents = await session_service.delete_subagents_for_messages(
            ctx.workspace,
            removed_message_ids,
        )
        for child_id in _subagent_ids_from_messages(removed_messages):
            try:
                await session_service.delete_session(child_id)
            except SessionNotFound:
                continue
            deleted_subagents += 1
        return {
            "ok": True,
            "message_id": message_id,
            "removed": removed,
            "deleted_subagents": deleted_subagents,
        }


def _messages_removed_by_truncate(
    messages: list[dict],
    message_id: str,
    *,
    keep: bool,
) -> list[dict]:
    cutoff = -1
    for idx, msg in enumerate(messages):
        if msg.get("id") == message_id:
            cutoff = idx
            break
    if cutoff < 0:
        return []
    if keep:
        cutoff += 1
    return messages[cutoff:]


def _subagent_ids_from_messages(messages: list[dict]) -> set[str]:
    child_ids: set[str] = set()
    for msg in messages:
        result = msg.get("tool_result")
        if isinstance(result, str):
            child_ids.update(_SUBAGENT_RESULT_RE.findall(result))
        for tool_call in msg.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            meta = tool_call.get("tool_meta")
            if not isinstance(meta, dict):
                continue
            child_id = meta.get("child_session_id")
            if isinstance(child_id, str) and child_id:
                child_ids.add(child_id)
    return child_ids
