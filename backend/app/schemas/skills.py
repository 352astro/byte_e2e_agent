from typing import Literal

from pydantic import BaseModel


class SkillInfoResponse(BaseModel):
    name: str
    description: str
    source: Literal["builtin", "custom"] = "builtin"
    has_builtin: bool = False
    overrides_builtin: bool = False


class SkillListResponse(BaseModel):
    skills: list[SkillInfoResponse]


class SkillDetailResponse(SkillInfoResponse):
    content: str


class SkillUpsertRequest(BaseModel):
    name: str | None = None
    content: str
