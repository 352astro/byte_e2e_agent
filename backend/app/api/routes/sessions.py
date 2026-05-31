from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent.session.status import RuntimeStatus
from app.dependencies import get_project
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
from app.services.project import Project

router = APIRouter(prefix="/api")


class WorkspaceRestoreRequest(BaseModel):
    commit_sha: str
    set_head: bool = True


class MessageTruncateRequest(BaseModel):
    message_id: str
    keep: bool = False


@router.post("/session", response_model=CreateSessionResponse)
def create_session(project: Project = Depends(get_project)) -> dict:
    return project.create_session()


@router.get("/sessions", response_model=ListSessionsResponse)
def list_sessions(project: Project = Depends(get_project)) -> dict:
    return {"workspace": project.workspace, "sessions": project.list_sessions()}


@router.delete("/session/{sid}")
async def delete_session(sid: str, project: Project = Depends(get_project)):
    try:
        project.get_session(sid)  # raises KeyError if not found
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    await project.delete_session(sid)
    return {"ok": True}


@router.get("/session/{sid}/history", response_model=HistoryResponse)
def get_history(sid: str, project: Project = Depends(get_project)) -> dict:
    try:
        info = project.get_info(sid)
        history = project.get_history(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session": info, "history": history}


@router.get("/session/{sid}/status", response_model=StatusResponse)
async def session_status(sid: str, project: Project = Depends(get_project)):
    """Legacy status route. The returned state is global runtime state."""
    return runtime_status(project)


@router.get("/status", response_model=StatusResponse)
def runtime_status(project: Project = Depends(get_project)):
    """Lightweight check: is the global runtime currently running?"""
    return {"running": project.scheduler.status != RuntimeStatus.IDLE}


@router.get("/session/{sid}/recover", response_model=RecoverResponse)
async def recover_session(sid: str, project: Project = Depends(get_project)):
    """Return full session state for frontend recovery after refresh."""
    try:
        return project.get_recovery_state(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


# ── Shadow repo / commit routes ──────────────────────────


@router.get("/session/{sid}/commits", response_model=CommitsResponse)
async def list_commits(sid: str, project: Project = Depends(get_project)):
    """Return all shadow commits for this workspace."""
    try:
        project.get_session(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"commits": project.shadow_repo.list_commits(sid)}


@router.get("/session/{sid}/commits/{sha}", response_model=CommitDetail)
async def get_commit(sid: str, sha: str, project: Project = Depends(get_project)):
    """Return metadata for a specific commit."""
    try:
        project.get_session(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return project.shadow_repo.get_commit(sha)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Commit not found: {sha}")


@router.post(
    "/session/{sid}/workspace/restore",
    response_model=WorkspaceRestoreResponse,
)
async def restore_commit(
    sid: str,
    req: WorkspaceRestoreRequest,
    project: Project = Depends(get_project),
):
    """Restore workspace to a shadow commit without modifying messages."""
    try:
        project.get_session(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        project.shadow_repo.restore(req.commit_sha)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"Commit not found: {req.commit_sha}"
        )
    if req.set_head:
        project.shadow_repo.set_head(sid, req.commit_sha)
    return {"ok": True, "commit_sha": req.commit_sha}


@router.post(
    "/session/{sid}/messages/truncate",
    response_model=MessageTruncateResponse,
)
async def truncate_messages(
    sid: str,
    req: MessageTruncateRequest,
    project: Project = Depends(get_project),
):
    """Truncate message history without modifying workspace commits."""
    try:
        session = project.get_session(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    removed = session.truncate_by_id(req.message_id, keep=req.keep)
    return {
        "ok": True,
        "message_id": req.message_id,
        "removed": removed,
    }


@router.post("/session/{sid}/interrupt", response_model=InterruptResponse)
async def interrupt_session(sid: str, project: Project = Depends(get_project)):
    """Interrupt the running agent loop for this session."""
    try:
        project.get_session(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    ok = await project.scheduler.interrupt()
    return {"ok": ok}


@router.post("/interrupt", response_model=InterruptResponse)
async def interrupt_global(project: Project = Depends(get_project)):
    """Interrupt whatever session is currently running (no session ID needed)."""
    ok = await project.scheduler.interrupt()
    return {"ok": ok}
