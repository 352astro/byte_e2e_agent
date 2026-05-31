from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import (
    get_checkpoint_service,
    get_session_service,
    get_workspace_service,
)
from app.services.checkpoint_service import CheckpointService
from app.services.session_service import SessionService
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/api")


class CheckoutRequest(BaseModel):
    commit_sha: str | None = None
    keep: bool = False
    truncate_tid: str | None = None
    keep_tid: bool = False


@router.post("/session")
def create_session(
    session_service: SessionService = Depends(get_session_service),
) -> dict:
    return session_service.create_session()


@router.get("/sessions")
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
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@router.get("/session/{sid}/history")
def get_history(
    sid: str,
    session_service: SessionService = Depends(get_session_service),
) -> dict:
    try:
        info = session_service.get_info(sid)
        history = session_service.get_history(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session": info, "history": history}


@router.get("/session/{sid}/status")
async def session_status(
    sid: str,
    session_service: SessionService = Depends(get_session_service),
):
    """Lightweight check: is the scheduler currently running this session?"""
    try:
        return session_service.get_session_status(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


@router.get("/session/{sid}/recover")
async def recover_session(
    sid: str,
    session_service: SessionService = Depends(get_session_service),
):
    """Return full session state for frontend recovery after refresh."""
    try:
        return session_service.get_recovery_state(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


# ── Shadow repo / commit routes ──────────────────────────


@router.get("/session/{sid}/commits")
async def list_commits(
    sid: str,
    checkpoint_service: CheckpointService = Depends(get_checkpoint_service),
):
    """Return all shadow commits for this workspace."""
    try:
        commits = checkpoint_service.list_commits(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"commits": commits}


@router.get("/session/{sid}/commits/{sha}")
async def get_commit(
    sid: str,
    sha: str,
    checkpoint_service: CheckpointService = Depends(get_checkpoint_service),
):
    """Return metadata for a specific commit."""
    try:
        return checkpoint_service.get_commit(sid, sha)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Commit not found: {sha}")


@router.post("/session/{sid}/checkout")
async def checkout_commit(
    sid: str,
    req: CheckoutRequest,
    checkpoint_service: CheckpointService = Depends(get_checkpoint_service),
):
    """Restore workspace and truncate transcripts at the given commit."""
    try:
        return await checkpoint_service.checkout_session(sid, req)
    except KeyError as exc:
        detail = str(exc)
        if "Session not found" in detail:
            raise HTTPException(status_code=404, detail="Session not found")
        raise HTTPException(status_code=404, detail=detail)


@router.post("/session/{sid}/interrupt")
async def interrupt_session(
    sid: str,
    session_service: SessionService = Depends(get_session_service),
):
    """Interrupt the running agent loop for this session."""
    try:
        ok = await session_service.interrupt_session(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": ok}


@router.post("/interrupt")
async def interrupt_global(
    session_service: SessionService = Depends(get_session_service),
):
    """Interrupt whatever session is currently running (no session ID needed)."""
    ok = await session_service.interrupt_current()
    return {"ok": ok}
