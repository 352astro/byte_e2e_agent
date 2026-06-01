"""Chat execution, SSE stream sources, and human-in-the-loop responses."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from agent.hook.stream_driver import StreamDriverHook
from agent.session import Session
from app.services.context import WorkspaceContext
from app.services.errors import AgentBusy, PendingRequestNotFound, SessionNotFound
from app.services.session_scope import SessionLocator
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
        self._locator = SessionLocator(ctx)

    def start_chat(
        self, session_id: str, question: str, max_steps: int
    ) -> ActiveStream:
        try:
            scope = self._locator.resolve(session_id)
            ctx = self._ctx.scoped(scope.workspace)
            ctx.get_session(session_id)
        except (KeyError, SessionNotFound) as exc:
            raise SessionNotFound(session_id) from exc
        driver = ctx.stream_driver
        queue = driver.subscribe(session_id)
        entry = ctx.create_runtime_session_entry(session_id)
        try:
            ctx.scheduler.start(
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
            scope = self._locator.resolve(session_id)
            ctx = self._ctx.scoped(scope.workspace)
            session = ctx.get_session(session_id)
        except (KeyError, SessionNotFound) as exc:
            raise SessionNotFound(session_id) from exc
        return SessionStream(
            session=session,
            driver=ctx.stream_driver,
        )

    async def respond_to_pending(
        self, session_id: str, message_id: str, response: dict
    ) -> None:
        try:
            scope = self._locator.resolve(session_id)
            ctx = self._ctx.scoped(scope.workspace)
            await ctx.scheduler.resolve(message_id, response)
        except KeyError as exc:
            raise PendingRequestNotFound(message_id) from exc
