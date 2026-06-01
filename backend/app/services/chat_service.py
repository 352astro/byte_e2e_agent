"""Chat execution, SSE stream sources, and human-in-the-loop responses."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from agent.hook.stream_driver import StreamDriverHook
from agent.session import Session
from app.services.context import WorkspaceContext
from app.services.errors import AgentBusy, PendingRequestNotFound, SessionNotFound
from shared.types import StreamEvent


@dataclass
class ActiveStream:
    driver: StreamDriverHook
    queue: "asyncio.Queue[StreamEvent | None]"


@dataclass
class SessionStream:
    session: Session
    driver: StreamDriverHook | None


class ChatService:
    def __init__(self, ctx: WorkspaceContext) -> None:
        self._ctx = ctx

    def start_chat(
        self, session_id: str, question: str, max_steps: int
    ) -> ActiveStream:
        try:
            self._ctx.get_session(session_id)
        except KeyError as exc:
            raise SessionNotFound(session_id) from exc
        driver = self._ctx.stream_driver
        queue = driver.subscribe(session_id)
        entry = self._ctx.create_runtime_session_entry(session_id)
        try:
            self._ctx.scheduler.start(
                entry,
                question,
                max_steps=max_steps,
            )
        except RuntimeError as exc:
            driver.unsubscribe(queue)
            raise AgentBusy(str(exc)) from exc
        return ActiveStream(driver=driver, queue=queue)

    def get_stream(self, session_id: str) -> SessionStream:
        try:
            session = self._ctx.get_session(session_id)
        except KeyError as exc:
            raise SessionNotFound(session_id) from exc
        return SessionStream(
            session=session,
            driver=self._ctx.stream_driver,
        )

    async def respond_to_pending(self, message_id: str, response: dict) -> None:
        try:
            await self._ctx.scheduler.resolve(message_id, response)
        except KeyError as exc:
            raise PendingRequestNotFound(message_id) from exc
