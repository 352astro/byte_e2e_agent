import json
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from session_manager import SessionManager

load_dotenv()

_AGENT_WORKSPACE = os.environ.get("AGENT_WORKSPACE", os.getcwd())

sessions = SessionManager(_AGENT_WORKSPACE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield  # startup — nothing to do yet
    sessions.save()  # shutdown


app = FastAPI(title="Byte E2E Agent Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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


# ── Session management ──────────────────────────────────


@app.post("/api/session")
def create_session() -> dict:
    sid = sessions.create()
    return {"session_id": sid}


@app.get("/api/sessions")
def list_sessions() -> dict:
    return {"sessions": sessions.list_ids()}


# ── Chat (SSE streaming) ────────────────────────────────


class ChatRequest(BaseModel):
    question: str = Field(..., description="Question or task for the agent")
    max_steps: int = Field(default=50, ge=1, le=200, description="Max reasoning steps")


@app.get("/api/session/{sid}/history")
def get_history(sid: str) -> dict:
    try:
        history = sessions.get_history(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"history": history}


@app.post("/api/session/{sid}/chat")
async def chat(sid: str, req: ChatRequest):
    try:
        agent = sessions.get(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator():
        try:
            async for event in agent.run_stream(req.question, max_steps=req.max_steps):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Legacy (stateless, backward compat) ─────────────────


class AgentStreamRequest(BaseModel):
    question: str = Field(..., description="Question or task for the agent")
    max_steps: int = Field(default=50, ge=1, le=200, description="Max reasoning steps")


@app.post("/api/agent/stream")
async def agent_stream(req: AgentStreamRequest):
    sid = sessions.create()

    async def event_generator():
        try:
            agent = sessions.get(sid)
            async for event in agent.run_stream(req.question, max_steps=req.max_steps):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            await sessions.delete(sid)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
