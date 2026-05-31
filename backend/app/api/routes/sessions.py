from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import get_project
from app.services.project import Project

router = APIRouter(prefix="/api")


class CheckoutRequest(BaseModel):
    commit_sha: str | None = None
    keep: bool = False
    truncate_tid: str | None = None
    keep_tid: bool = False


@router.post("/session")
def create_session(project: Project = Depends(get_project)) -> dict:
    return project.create_session()


@router.get("/sessions")
def list_sessions(project: Project = Depends(get_project)) -> dict:
    return {"workspace": project.workspace, "sessions": project.list_sessions()}


@router.delete("/session/{sid}")
async def delete_session(sid: str, project: Project = Depends(get_project)):
    try:
        await project.delete_session(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@router.get("/session/{sid}/history")
def get_history(sid: str, project: Project = Depends(get_project)) -> dict:
    try:
        info = project.get_info(sid)
        history = project.get_history(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session": info, "history": history}


@router.get("/session/{sid}/status")
async def session_status(sid: str, project: Project = Depends(get_project)):
    """Lightweight check: is the scheduler currently running this session?"""
    try:
        return project.get_session_status(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


@router.get("/session/{sid}/recover")
async def recover_session(sid: str, project: Project = Depends(get_project)):
    """Return full session state for frontend recovery after refresh."""
    try:
        return project.get_recovery_state(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


# ── Shadow repo / commit routes ──────────────────────────


@router.get("/session/{sid}/commits")
async def list_commits(sid: str, project: Project = Depends(get_project)):
    """Return all shadow commits for this workspace."""
    try:
        commits = project.list_commits(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"commits": commits}


@router.get("/session/{sid}/commits/{sha}")
async def get_commit(sid: str, sha: str, project: Project = Depends(get_project)):
    """Return metadata for a specific commit."""
    try:
        return project.get_commit(sid, sha)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Commit not found: {sha}")


@router.post("/session/{sid}/checkout")
async def checkout_commit(
    sid: str,
    req: CheckoutRequest,
    project: Project = Depends(get_project),
):
    """Restore workspace and truncate transcripts at the given commit."""
    try:
        return await project.checkout_session(sid, req)
    except KeyError as exc:
        detail = str(exc)
        if "Session not found" in detail:
            raise HTTPException(status_code=404, detail="Session not found")
        raise HTTPException(status_code=404, detail=detail)


@router.post("/session/{sid}/interrupt")
async def interrupt_session(sid: str, project: Project = Depends(get_project)):
    """Interrupt the running agent loop for this session."""
    try:
        ok = await project.interrupt_session(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": ok}


@router.post("/interrupt")
async def interrupt_global(project: Project = Depends(get_project)):
    """Interrupt whatever session is currently running (no session ID needed)."""
    ok = await project.interrupt_current()
    return {"ok": ok}
