from pydantic import BaseModel, Field

from agent.core.config import ToolSetPreset


class CreateSessionRequest(BaseModel):
    name: str = ""
    preamble: str = ""
    rules: list[str] = Field(default_factory=list)
    preloaded_skills: list[str] = Field(default_factory=list)
    tool_set_preset: ToolSetPreset = ToolSetPreset.ALL
    custom_tools: list[str] = Field(default_factory=list)


from app.schemas.settings import SessionRule, SessionSettings  # noqa: E402,F401
from app.schemas.skills import (  # noqa: E402,F401
    SkillDetailResponse,
    SkillInfoResponse,
    SkillListResponse,
    SkillUpsertRequest,
)
from app.schemas.sysguard import (  # noqa: E402,F401
    SysguardRuleMode,
    SysguardRuleRequest,
    SysguardRuleResponse,
    SysguardSettingsResponse,
)
from app.schemas.tools import (  # noqa: E402,F401
    ToolInfoResponse,
    ToolPermissionMode,
    ToolPermissionSettings,
    ToolPresetListResponse,
    ToolPresetResponse,
)
