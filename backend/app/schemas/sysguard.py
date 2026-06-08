from typing import Literal

from pydantic import BaseModel, Field

SysguardRuleMode = Literal["readonly", "readonly_exec", "readwrite"]


class SysguardRuleResponse(BaseModel):
    id: str
    label: str
    path: str
    mode: SysguardRuleMode = "readonly_exec"
    source: Literal["builtin", "global", "workspace"] = "builtin"
    enabled: bool = True
    description: str = ""


class SysguardSettingsResponse(BaseModel):
    builtin: list[SysguardRuleResponse] = Field(default_factory=list)
    global_: list[SysguardRuleResponse] = Field(default_factory=list, alias="global")
    workspace: list[SysguardRuleResponse] = Field(default_factory=list)


class SysguardRuleRequest(BaseModel):
    label: str
    path: str
    mode: SysguardRuleMode = "readonly_exec"
    enabled: bool = True
    description: str = ""
