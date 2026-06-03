from pydantic import BaseModel, Field


class SetWorkspaceRequest(BaseModel):
    path: str = Field(..., description="Absolute or relative path to new workspace")


class WorkspacePwdResponse(BaseModel):
    workspace: str
    home: str
    roots: list[str]


class WorkspaceDirectoryEntry(BaseModel):
    name: str
    path: str
    kind: str
    hidden: bool
    readable: bool
    size: int | None = None
    modified_at: float | None = None


class WorkspaceDirectoryResponse(BaseModel):
    path: str
    parent: str | None
    home: str
    roots: list[str]
    entries: list[WorkspaceDirectoryEntry]
