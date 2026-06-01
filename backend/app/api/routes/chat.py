"""Chat routes — SSE streaming via StreamDriverHook."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException

from app.api.sse import sse_response
from app.dependencies import get_chat_service
from app.schemas.chat import ChatRequest, RespondRequest
from app.services.chat_service import ChatService
from app.services.errors import (
    AgentBusy,
    AmbiguousSession,
    PendingRequestNotFound,
    SessionNotFound,
)
from shared.types import StreamEvent, StreamEventKind

router = APIRouter(prefix="/api/session/{sid}")


def _sse_event_line(event) -> str:
    data = event.model_dump(mode="json")
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _message_replay_events(msg: dict, session_id: str = ""):
    msg_id = msg.get("id", "")
    turn_id = msg.get("turn_id", "")
    role = msg.get("role", "")

    yield StreamEvent(
        kind=StreamEventKind.MESSAGE_START,
        session_id=session_id,
        message_id=msg_id,
        turn_id=turn_id,
        role=role,
    )

    content = msg.get("content", "")
    if content:
        yield StreamEvent.chunk_delta(msg_id, "content", content, session_id=session_id)
        yield StreamEvent.chunk_complete(
            msg_id, "content", content, session_id=session_id
        )

    reasoning = msg.get("reasoning", "")
    if reasoning:
        yield StreamEvent.chunk_delta(
            msg_id, "reasoning", reasoning, session_id=session_id
        )
        yield StreamEvent.chunk_complete(
            msg_id, "reasoning", reasoning, session_id=session_id
        )

    for i, tc in enumerate(msg.get("tool_calls", []) or []):
        fn = tc.get("function", {})
        name = fn.get("name", "")
        args = fn.get("arguments", "")
        if name:
            yield StreamEvent.chunk_delta(
                msg_id,
                "tool_calls",
                name,
                tool_name=name,
                tool_index=i,
                sub_field="name",
                session_id=session_id,
            )
        if args:
            yield StreamEvent.chunk_delta(
                msg_id,
                "tool_calls",
                args,
                tool_name=name,
                tool_index=i,
                sub_field="args",
                session_id=session_id,
            )
        yield StreamEvent.chunk_complete(
            msg_id,
            "tool_calls",
            args,
            tool_name=name,
            tool_args=args,
            session_id=session_id,
        )

    tool_result = msg.get("tool_result", "")
    if tool_result:
        yield StreamEvent.chunk_delta(
            msg_id, "tool_result", tool_result, session_id=session_id
        )
        yield StreamEvent.chunk_complete(
            msg_id,
            "tool_result",
            tool_result,
            tool_name=msg.get("tool_name", ""),
            is_error=bool(msg.get("error", "")),
            session_id=session_id,
        )

    yield StreamEvent.message_finish(msg_id, session_id=session_id)


@router.post("/chat")
async def chat(
    sid: str,
    req: ChatRequest,
    chat_service: ChatService = Depends(get_chat_service),
):
    """Start a chat turn and return its SSE stream."""
    try:
        stream = chat_service.start_chat(sid, req.question, req.max_steps)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found")
    except AmbiguousSession as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except AgentBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    q = stream.queue

    async def event_generator():
        try:
            while True:
                ev = await q.get()
                if ev is None:
                    break
                yield _sse_event_line(ev)
        except asyncio.CancelledError:
            pass
        finally:
            stream.driver.unsubscribe(q)

    return sse_response(event_generator())


@router.get("/stream")
async def stream_events(
    sid: str,
    chat_service: ChatService = Depends(get_chat_service),
):
    """SSE reconnect. Replay persisted messages, then subscribe to live events."""
    try:
        stream = chat_service.get_stream(sid)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found")
    except AmbiguousSession as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    driver = stream.driver
    session = stream.session

    async def event_generator():
        for msg in session.get_messages():
            for ev in _message_replay_events(msg, sid):
                yield _sse_event_line(ev)

        if driver is None:
            return

        q = driver.subscribe(sid)
        try:
            while True:
                ev = await q.get()
                if ev is None:
                    break
                yield _sse_event_line(ev)
        except asyncio.CancelledError:
            pass
        finally:
            driver.unsubscribe(q)

    return sse_response(event_generator())


@router.post("/respond")
async def respond(
    sid: str,
    req: RespondRequest,
    chat_service: ChatService = Depends(get_chat_service),
):
    try:
        await chat_service.respond_to_pending(sid, req.message_id, req.response)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found")
    except AmbiguousSession as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except PendingRequestNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}
