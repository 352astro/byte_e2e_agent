from typing import Literal

from pydantic import BaseModel, Field

from agent.core.config import ToolSetPreset

ToolPermissionMode = Literal["allow", "ask", "deny"]


class ToolInfoResponse(BaseModel):
    name: str
    description: str


class ToolPresetResponse(BaseModel):
    name: ToolSetPreset
    tools: list[str]


class ToolPresetListResponse(BaseModel):
    presets: list[ToolPresetResponse]
    tools: list[ToolInfoResponse]


class ToolPermissionSettings(BaseModel):
    tools: dict[str, ToolPermissionMode] = Field(default_factory=dict)
