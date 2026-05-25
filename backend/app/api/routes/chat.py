import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.api.sse import sse_line, sse_response, yield_transcripts_as_flush
from app.dependencies import get_project
from app.schemas.chat import ChatRequest, RespondRequest
from app.services.project import Project

router = APIRouter(prefix="/api/session/{sid}")


@router.post("/chat")
async def chat(
    sid: str,
    req: ChatRequest,
    project: Project = Depends(get_project),
):
    """Start execution and return SSE stream directly.

    subscribe-before-start: channel created, subscribed, THEN
    scheduler starts. No events are lost.
    """
    try:
        stream = project.start_chat(sid, req.question, req.max_steps)
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
async def stream_events(sid: str, project: Project = Depends(get_project)):
    """SSE for reconnection. Subscribe-first, then catch-up, then live."""
    try:
        stream = project.get_stream(sid)
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
            for tid, text in channel.get_buffered().items():
                yield sse_line(
                    {
                        "event": "chunk",
                        "transcript_id": tid,
                        "text": text,
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
    project: Project = Depends(get_project),
):
    try:
        scheduler = project.scheduler
        scheduler.resolve(req.transcript_id, req.response)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}
