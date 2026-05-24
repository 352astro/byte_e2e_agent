from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_project
from app.schemas.workspace import SetWorkspaceRequest
from app.services.project import Project

router = APIRouter(prefix="/api/workspace")


@router.get("")
def get_workspace(project: Project = Depends(get_project)) -> dict:
    return {"workspace": project.workspace}


@router.post("/set")
def set_workspace(
    req: SetWorkspaceRequest,
    project: Project = Depends(get_project),
) -> dict:
    try:
        project.set_workspace(req.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"workspace": project.workspace}
