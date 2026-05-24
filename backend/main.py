import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from session_manager import SessionManager

load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_AGENT_WORKSPACE = os.environ.get("AGENT_WORKSPACE", str(_PROJECT_ROOT))

sessions = SessionManager(_AGENT_WORKSPACE)


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


@app.post("/api/workspace/set")
def set_workspace(req: SetWorkspaceRequest) -> dict:
    """Validate and apply a workspace path sent from the frontend."""
    try:
        resolved = sessions.resolve_workspace(req.path)
        sessions.set_default_workspace(resolved)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"workspace": resolved}


# ── Session management ──────────────────────────────────


class CreateSessionRequest(BaseModel):
    workspace: str | None = Field(default=None, description="Workspace directory")


@app.post("/api/session")
def create_session(req: CreateSessionRequest | None = None) -> dict:
    try:
        return sessions.create(req.workspace if req else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/sessions")
def list_sessions(workspace: str | None = None) -> dict:
    try:
        resolved_workspace = sessions.resolve_workspace(workspace)
        sessions_info = sessions.list_info(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"workspace": resolved_workspace, "sessions": sessions_info}


# ── Chat (SSE streaming) ────────────────────────────────


class ChatRequest(BaseModel):
    question: str = Field(..., description="Question or task for the agent")
    max_steps: int = Field(default=50, ge=1, le=200, description="Max reasoning steps")
    workspace: str | None = Field(default=None, description="Workspace directory")


@app.get("/api/session/{sid}/history")
def get_history(sid: str, workspace: str | None = None) -> dict:
    try:
        info = sessions.get_info(sid, workspace)
        history = sessions.get_history(sid, workspace)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"session": info, "history": history}


@app.post("/api/session/{sid}/chat")
async def chat(sid: str, req: ChatRequest):
    try:
        agent = sessions.get(sid, req.workspace)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

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
    workspace: str | None = Field(default=None, description="Workspace directory")


@app.post("/api/agent/stream")
async def agent_stream(req: AgentStreamRequest):
    try:
        session = sessions.create(req.workspace)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    sid = session["session_id"]
    workspace = session["workspace"]

    async def event_generator():
        try:
            agent = sessions.get(sid, workspace)
            async for event in agent.run_stream(req.question, max_steps=req.max_steps):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            await sessions.delete(sid, workspace)

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
