from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_project
from app.services.project import Project

router = APIRouter(prefix="/api")


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
