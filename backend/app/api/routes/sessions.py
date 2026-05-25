from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import get_project
from app.services.project import Project

router = APIRouter(prefix="/api")


class CheckoutRequest(BaseModel):
    commit_sha: str


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
        project.get_session(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"commits": project.shadow_repo.list_commits()}


@router.get("/session/{sid}/commits/{sha}")
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


@router.post("/session/{sid}/checkout")
async def checkout_commit(
    sid: str,
    req: CheckoutRequest,
    project: Project = Depends(get_project),
):
    """Restore workspace to a specific commit."""
    try:
        project.get_session(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        project.shadow_repo.restore(req.commit_sha)
        return {"ok": True, "commit_sha": req.commit_sha}
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"Commit not found: {req.commit_sha}"
        )
