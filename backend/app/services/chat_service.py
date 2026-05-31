"""Chat execution, SSE stream sources, and human-in-the-loop responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.session import Session
from agent.transcript import TranscriptStream
from app.services.context import WorkspaceContext


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
        session = self._ctx.get_session(session_id)
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
        except RuntimeError:
            channel.unsubscribe(queue)
            raise
        return ActiveStream(channel=channel, queue=queue)

    def get_stream(self, session_id: str) -> SessionStream:
        return SessionStream(
            session=self._ctx.get_session(session_id),
            channel=self._ctx.scheduler.channel,
        )

    def respond_to_pending(self, transcript_id: str, response: dict) -> None:
        self._ctx.scheduler.resolve(transcript_id, response)
