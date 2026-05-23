import json
import os
import platform
import subprocess
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


def _select_folder(initial_dir: str) -> str | None:
    if platform.system() == "Darwin":
        apple_initial_dir = initial_dir.replace("\\", "\\\\").replace('"', '\\"')
        script = (
            'POSIX path of (choose folder with prompt "Select agent workspace" '
            f'default location POSIX file "{apple_initial_dir}")'
        )
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(
            title="Select agent workspace",
            initialdir=initial_dir,
            mustexist=True,
        )
    finally:
        root.destroy()
    return selected or None


class SelectWorkspaceRequest(BaseModel):
    current: str | None = Field(default=None, description="Current workspace directory")


@app.post("/api/workspace/select")
def select_workspace(req: SelectWorkspaceRequest | None = None) -> dict:
    try:
        initial_dir = sessions.resolve_workspace(req.current if req else None)
    except ValueError:
        initial_dir = sessions.default_workspace

    selected = _select_folder(initial_dir)
    if not selected:
        return {"workspace": initial_dir, "cancelled": True}

    try:
        workspace = sessions.resolve_workspace(selected)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"workspace": workspace, "cancelled": False}


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
