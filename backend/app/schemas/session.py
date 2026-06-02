from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    name: str = ""
    preamble: str = ""
    rules: list[str] = Field(default_factory=list)
    preloaded_skills: list[str] = Field(default_factory=list)


class SessionRule(BaseModel):
    id: str
    content: str


class SessionSettings(BaseModel):
    preamble: str = ""
    rules: list[SessionRule] = Field(default_factory=list)
    default_rule_ids: list[str] = Field(default_factory=list)
    default_skill_names: list[str] = Field(default_factory=list)


class SkillInfoResponse(BaseModel):
    name: str
    description: str


class SkillListResponse(BaseModel):
    skills: list[SkillInfoResponse]
