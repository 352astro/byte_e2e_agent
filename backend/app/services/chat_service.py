"""Chat execution, SSE stream sources, and human-in-the-loop responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.session import Session
from agent.transcript import TranscriptStream
from app.services.context import WorkspaceContext
from app.services.errors import (
    AgentBusy,
    PendingRequestNotFound,
    SessionNotFound,
    is_scheduler_busy_error,
)


@dataclass
class ActiveStream:
    channel: TranscriptStream
    queue: Any


@dataclass
class SessionStream:
    session: Session
    channel: TranscriptStream | None


class ChatService:
    def __init__(self, ctx: WorkspaceContext) -> None:
        self._ctx = ctx

    def start_chat(
        self, session_id: str, question: str, max_steps: int
    ) -> ActiveStream:
        try:
            session = self._ctx.get_session(session_id)
        except KeyError as exc:
            raise SessionNotFound(session_id) from exc
        channel = TranscriptStream()
        queue = channel.subscribe()
        try:
            self._ctx.scheduler.start(
                session,
                question,
                channel=channel,
                max_steps=max_steps,
                shadow_repo=self._ctx.shadow_repo,
            )
        except RuntimeError as exc:
            channel.unsubscribe(queue)
            if is_scheduler_busy_error(exc):
                raise AgentBusy() from exc
            raise
        return ActiveStream(channel=channel, queue=queue)

    def get_stream(self, session_id: str) -> SessionStream:
        try:
            session = self._ctx.get_session(session_id)
        except KeyError as exc:
            raise SessionNotFound(session_id) from exc
        return SessionStream(
            session=session,
            channel=self._ctx.scheduler.channel,
        )

    def respond_to_pending(self, transcript_id: str, response: dict) -> None:
        try:
            self._ctx.scheduler.resolve(transcript_id, response)
        except KeyError as exc:
            raise PendingRequestNotFound(transcript_id) from exc
