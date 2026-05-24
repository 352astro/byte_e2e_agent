from pydantic import BaseModel, Field


class SetWorkspaceRequest(BaseModel):
    path: str = Field(..., description="Absolute or relative path to new workspace")
