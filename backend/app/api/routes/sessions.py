from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import (
    get_checkpoint_service,
    get_session_service,
    get_workspace_service,
)
from app.schemas.response import (
    CommitDetail,
    CommitsResponse,
    CreateSessionResponse,
    HistoryResponse,
    InterruptResponse,
    ListSessionsResponse,
    MessageTruncateResponse,
    RecoverResponse,
    StatusResponse,
    WorkspaceRestoreResponse,
)
from app.services.checkpoint_service import CheckpointService
from app.services.errors import CommitNotFound, SessionNotFound
from app.services.session_service import SessionService
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/api")


class WorkspaceRestoreRequest(BaseModel):
    commit_sha: str
    set_head: bool = True


class MessageTruncateRequest(BaseModel):
    message_id: str
    keep: bool = False


@router.post("/session", response_model=CreateSessionResponse)
def create_session(
    session_service: SessionService = Depends(get_session_service),
) -> dict:
    return session_service.create_session()


@router.get("/sessions", response_model=ListSessionsResponse)
def list_sessions(
    workspace_service: WorkspaceService = Depends(get_workspace_service),
    session_service: SessionService = Depends(get_session_service),
) -> dict:
    return {
        "workspace": workspace_service.get_workspace(),
        "sessions": session_service.list_sessions(),
    }


@router.get("/sessions/all")
def list_all_sessions(
    workspace_service: WorkspaceService = Depends(get_workspace_service),
    session_service: SessionService = Depends(get_session_service),
) -> dict:
    return {
        "workspace": workspace_service.get_workspace(),
        "workspaces": workspace_service.list_registered_workspaces(),
        "sessions": session_service.list_all_sessions(),
    }


@router.delete("/session/{sid}")
async def delete_session(
    sid: str,
    session_service: SessionService = Depends(get_session_service),
):
    try:
        await session_service.delete_session(sid)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@router.get("/session/{sid}/history", response_model=HistoryResponse)
def get_history(
    sid: str,
    session_service: SessionService = Depends(get_session_service),
) -> dict:
    try:
        info = session_service.get_info(sid)
        history = session_service.get_history(sid)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session": info, "history": history}


@router.get("/session/{sid}/status", response_model=StatusResponse)
async def session_status(
    sid: str,
    session_service: SessionService = Depends(get_session_service),
):
    """Legacy session status route."""
    try:
        return session_service.get_session_status(sid)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found")


@router.get("/status", response_model=StatusResponse)
def runtime_status(
    session_service: SessionService = Depends(get_session_service),
):
    """Lightweight check: is the global runtime currently running?"""
    return session_service.get_runtime_status()


@router.get("/session/{sid}/recover", response_model=RecoverResponse)
async def recover_session(
    sid: str,
    session_service: SessionService = Depends(get_session_service),
):
    """Return full session state for frontend recovery after refresh."""
    try:
        return session_service.get_recovery_state(sid)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found")


@router.get("/session/{sid}/commits", response_model=CommitsResponse)
async def list_commits(
    sid: str,
    checkpoint_service: CheckpointService = Depends(get_checkpoint_service),
):
    """Return all shadow commits for this workspace."""
    try:
        return {"commits": checkpoint_service.list_commits(sid)}
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found")


@router.get("/session/{sid}/commits/{sha}", response_model=CommitDetail)
async def get_commit(
    sid: str,
    sha: str,
    checkpoint_service: CheckpointService = Depends(get_checkpoint_service),
):
    """Return metadata for a specific commit."""
    try:
        return checkpoint_service.get_commit(sid, sha)
    except CommitNotFound:
        raise HTTPException(status_code=404, detail=f"Commit not found: {sha}")


@router.post(
    "/session/{sid}/workspace/restore",
    response_model=WorkspaceRestoreResponse,
)
async def restore_commit(
    sid: str,
    req: WorkspaceRestoreRequest,
    checkpoint_service: CheckpointService = Depends(get_checkpoint_service),
):
    """Restore workspace to a shadow commit without modifying messages."""
    try:
        return checkpoint_service.restore_workspace(
            sid,
            req.commit_sha,
            set_head=req.set_head,
        )
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found")
    except CommitNotFound:
        raise HTTPException(
            status_code=404, detail=f"Commit not found: {req.commit_sha}"
        )


@router.post(
    "/session/{sid}/messages/truncate",
    response_model=MessageTruncateResponse,
)
async def truncate_messages(
    sid: str,
    req: MessageTruncateRequest,
    checkpoint_service: CheckpointService = Depends(get_checkpoint_service),
):
    """Truncate message history without modifying workspace commits."""
    try:
        return checkpoint_service.truncate_messages(
            sid,
            req.message_id,
            keep=req.keep,
        )
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found")


@router.post("/session/{sid}/interrupt", response_model=InterruptResponse)
async def interrupt_session(
    sid: str,
    session_service: SessionService = Depends(get_session_service),
):
    """Interrupt the running agent loop for this session."""
    try:
        ok = await session_service.interrupt_session(sid)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": ok}


@router.post("/interrupt", response_model=InterruptResponse)
async def interrupt_global(
    session_service: SessionService = Depends(get_session_service),
):
    """Interrupt whatever session is currently running (no session ID needed)."""
    ok = await session_service.interrupt_current()
    return {"ok": ok}
