from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.dependencies import get_workspace_service
from app.schemas.workspace import (
    SetWorkspaceRequest,
    WorkspaceDirectoryResponse,
    WorkspacePwdResponse,
)
from app.services.errors import AgentBusy
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/api/workspace")


@router.get("")
def get_workspace(
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> dict:
    return {"workspace": workspace_service.get_workspace()}


@router.get("/pwd", response_model=WorkspacePwdResponse)
def get_workspace_pwd(
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> dict:
    return workspace_service.get_picker_context()


@router.get("/ls", response_model=WorkspaceDirectoryResponse)
def list_workspace_directory(
    path: str | None = None,
    show_hidden: bool = False,
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> dict:
    try:
        return workspace_service.list_directory(path, show_hidden=show_hidden)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/file")
def get_workspace_file(
    path: str,
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> FileResponse:
    try:
        resolved = workspace_service.resolve_file(path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(resolved, media_type=_guess_media_type(resolved))


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


def _guess_media_type(path: Path) -> str | None:
    mapping = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".bmp": "image/bmp",
        ".ico": "image/x-icon",
    }
    return mapping.get(path.suffix.lower())
