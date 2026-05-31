import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.api.sse import sse_line, sse_response, yield_transcripts_as_flush
from app.dependencies import get_chat_service
from app.schemas.chat import ChatRequest, RespondRequest
from app.services.chat_service import ChatService

router = APIRouter(prefix="/api/session/{sid}")


@router.post("/chat")
async def chat(
    sid: str,
    req: ChatRequest,
    chat_service: ChatService = Depends(get_chat_service),
):
    """Start execution and return SSE stream directly.

    subscribe-before-start: channel created, subscribed, THEN
    scheduler starts. No events are lost.
    """
    try:
        stream = chat_service.start_chat(sid, req.question, req.max_steps)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    q = stream.queue

    async def event_generator():
        try:
            while True:
                ev = await q.get()
                if ev is None:
                    break
                yield sse_line({"event": ev.name, **ev.payload})
        except asyncio.CancelledError:
            pass
        finally:
            stream.channel.unsubscribe(q)

    return sse_response(event_generator())


@router.get("/stream")
async def stream_events(
    sid: str,
    chat_service: ChatService = Depends(get_chat_service),
):
    """SSE for reconnection. Subscribe-first, then catch-up, then live."""
    try:
        stream = chat_service.get_stream(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    session = stream.session
    channel = stream.channel

    async def event_generator():
        if channel is None:
            for line in yield_transcripts_as_flush(session):
                yield line
            return

        q = channel.subscribe()
        try:
            for tid, sub_streams in channel.get_buffered().items():
                for ss in sub_streams:
                    yield sse_line(
                        {
                            "event": "chunk",
                            "transcript_id": tid,
                            "id": ss["id"],
                            "kind": ss["kind"],
                            "text": ss["text"],
                        }
                    )
            for line in yield_transcripts_as_flush(session):
                yield line
            while True:
                ev = await q.get()
                if ev is None:
                    break
                yield sse_line({"event": ev.name, **ev.payload})
        except asyncio.CancelledError:
            pass
        finally:
            channel.unsubscribe(q)

    return sse_response(event_generator())


@router.post("/respond")
async def respond(
    sid: str,
    req: RespondRequest,
    chat_service: ChatService = Depends(get_chat_service),
):
    try:
        chat_service.respond_to_pending(req.transcript_id, req.response)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}
