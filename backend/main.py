import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent.stream_channel import StreamChannel, StreamEvent
from project import Project

load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_AGENT_WORKSPACE = os.environ.get("AGENT_WORKSPACE", str(_PROJECT_ROOT))

project = Project(_AGENT_WORKSPACE)


app = FastAPI(title="Byte E2E Agent Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Hello World from FastAPI!"}


@app.get("/api/hello")
def hello() -> dict[str, str]:
    return {"message": "Hello World from FastAPI!", "status": "ok"}


# ── Workspace management ────────────────────────────────


class SetWorkspaceRequest(BaseModel):
    path: str = Field(..., description="Absolute or relative path to new workspace")


@app.get("/api/workspace")
def get_workspace() -> dict:
    return {"workspace": project.workspace}


@app.post("/api/workspace/set")
def set_workspace(req: SetWorkspaceRequest) -> dict:
    try:
        project.set_workspace(req.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"workspace": project.workspace}


# ── Session management ──────────────────────────────────


@app.post("/api/session")
def create_session() -> dict:
    return project.create_session()


@app.get("/api/sessions")
def list_sessions() -> dict:
    return {"workspace": project.workspace, "sessions": project.list_sessions()}


@app.delete("/api/session/{sid}")
async def delete_session(sid: str):
    try:
        await project.delete_session(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


# ── History ───────────────────────────────────────────


@app.get("/api/session/{sid}/history")
def get_history(sid: str) -> dict:
    try:
        info = project.get_info(sid)
        history = project.get_history(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session": info, "history": history}


# ── SSE helpers ────────────────────────────────────────


def _sse_line(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _sse_response(generator):
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _yield_transcripts_as_flush(session):
    """Yield all session transcripts as flush SSE lines."""
    for t in session.get_transcripts():
        yield _sse_line(
            {
                "event": "flush",
                "transcript_id": t["id"],
                "kind": t["kind"],
                "message": t["message"],
            }
        )


# ── Chat (start execution → SSE) ───────────────────────


class ChatRequest(BaseModel):
    question: str = Field(..., description="Question or task for the agent")
    max_steps: int = Field(default=50, ge=1, le=200, description="Max reasoning steps")


@app.post("/api/session/{sid}/chat")
async def chat(sid: str, req: ChatRequest):
    """Start execution and return SSE stream directly.

    subscribe-before-start: channel created, subscribed, THEN
    scheduler starts. No events are lost.
    """
    try:
        session = project.get_session(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    scheduler = project.scheduler

    # 1. create channel
    channel = StreamChannel()

    # 2. subscribe BEFORE start (task won't run until we await)
    q = channel.subscribe()

    # 3. start — task is scheduled but hasn't emitted yet
    try:
        scheduler.start(session, req.question, channel=channel)
    except RuntimeError as exc:
        channel.unsubscribe(q)
        raise HTTPException(status_code=409, detail=str(exc))

    async def event_generator():
        try:
            while True:
                ev: StreamEvent | None = await q.get()
                if ev is None:
                    break
                yield _sse_line({"event": ev.name, **ev.payload})
        except asyncio.CancelledError:
            pass
        finally:
            channel.unsubscribe(q)

    return _sse_response(event_generator())


# ── Stream (SSE, for reconnection after refresh) ────────


@app.get("/api/session/{sid}/stream")
async def stream_events(sid: str):
    """SSE for reconnection. Subscribe-first, then catch-up, then live.

    Frontend uses this after calling /recover (to get initial state).
    Subscribe happens BEFORE catch-up so no events are lost in between.
    Frontend deduplicates by transcript_id.
    """
    scheduler = project.scheduler

    try:
        session = project.get_session(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    channel = scheduler.channel

    async def event_generator():
        # Not running → replay all transcripts and close
        if channel is None:
            for line in _yield_transcripts_as_flush(session):
                yield line
            return

        # ★ subscribe first, then catch up
        q = channel.subscribe()
        try:
            # catch-up: buffered chunks (in-progress)
            for tid, text in channel.get_buffered().items():
                yield _sse_line(
                    {
                        "event": "chunk",
                        "transcript_id": tid,
                        "text": text,
                    }
                )
            # catch-up: completed transcripts
            for line in _yield_transcripts_as_flush(session):
                yield line
            # live events
            while True:
                ev: StreamEvent | None = await q.get()
                if ev is None:
                    break
                yield _sse_line({"event": ev.name, **ev.payload})
        except asyncio.CancelledError:
            pass
        finally:
            channel.unsubscribe(q)

    return _sse_response(event_generator())


# ── Recover ────────────────────────────────────────────


@app.get("/api/session/{sid}/recover")
async def recover_session(sid: str):
    """Return full session state for frontend recovery after refresh."""
    try:
        session = project.get_session(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    scheduler = project.scheduler
    channel = scheduler.channel
    is_running = (
        scheduler.state != "idle"
        and scheduler._current_session is not None
        and scheduler._current_session.session_id == sid
    )

    return {
        "transcripts": session.get_transcripts(),
        "buffered": channel.get_buffered() if (is_running and channel) else {},
        "running": is_running,
    }


# ── Respond (permission prompts) ────────────────────────


class RespondRequest(BaseModel):
    transcript_id: str = Field(..., description="Transcript ID to respond to")
    response: dict = Field(..., description="User response payload")


@app.post("/api/session/{sid}/respond")
async def respond(sid: str, req: RespondRequest):
    try:
        scheduler = project.scheduler
        scheduler.resolve(req.transcript_id, req.response)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
