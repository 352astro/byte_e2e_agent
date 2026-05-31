from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_workspace_service
from app.schemas.workspace import SetWorkspaceRequest
from app.services.errors import AgentBusy
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/api/workspace")


@router.get("")
def get_workspace(
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> dict:
    return {"workspace": workspace_service.get_workspace()}


@router.post("/set")
def set_workspace(
    req: SetWorkspaceRequest,
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> dict:
    try:
        workspace_service.set_workspace(req.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except AgentBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"workspace": workspace_service.get_workspace()}
