from pydantic import BaseModel, Field


class SessionRule(BaseModel):
    id: str
    content: str


class SessionSettings(BaseModel):
    preamble: str = ""
    rules: list[SessionRule] = Field(default_factory=list)
    default_rule_ids: list[str] = Field(default_factory=list)
    default_skill_names: list[str] = Field(default_factory=list)
