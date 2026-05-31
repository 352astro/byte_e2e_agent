"""ShadowCommitHook — creates workspace commits from message lifecycle events."""

from __future__ import annotations

import asyncio
import logging

from agent.shadow_repo import ShadowRepo
from shared.hooks import BaseHook
from shared.types import Message, MessageRole

logger = logging.getLogger(__name__)


class ShadowCommitHook(BaseHook):
    """Fire-and-forget workspace snapshot hook.

    Message remains the source of truth for conversation state. This hook only
    borrows user message content as a commit title for the independent shadow
    repo timeline.
    """

    def __init__(self, shadow_repo: ShadowRepo) -> None:
        self._shadow_repo = shadow_repo
        self._lock = asyncio.Lock()

    async def on_turn_start(self, *, session_id: str, **kwargs) -> None:
        async with self._lock:
            self._ensure_initial(session_id)

    async def on_message_finish(
        self,
        *,
        msg: Message,
        session_id: str = "",
        **kwargs,
    ) -> None:
        if not session_id or msg.role != MessageRole.USER:
            return
        title = _commit_title(msg.content)
        if not title:
            return
        async with self._lock:
            self._ensure_initial(session_id)
            try:
                self._shadow_repo.snapshot(session_id, title)
            except Exception:
                logger.exception("Failed to create shadow commit")

    def _ensure_initial(self, session_id: str) -> None:
        try:
            if self._shadow_repo.list_commits(session_id):
                return
            self._shadow_repo.snapshot(session_id, "Initial workspace state")
        except Exception:
            logger.exception("Failed to create initial shadow commit")


def _commit_title(content: str) -> str:
    for line in content.splitlines():
        title = line.strip()
        if title:
            return title[:200]
    return ""
