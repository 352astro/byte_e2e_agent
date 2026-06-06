from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent.core.config import ToolSetPreset
from agent.tools import tool_registry
from agent.tools.skill import (
    create_custom_skill,
    delete_custom_skill,
    read_skill_detail,
    restore_builtin_skill,
    scan_skills,
    upsert_custom_skill,
)
from app.dependencies import get_settings_service
from app.schemas.session import (
    SessionSettings,
    SkillDetailResponse,
    SkillListResponse,
    SkillUpsertRequest,
    SysguardRuleRequest,
    SysguardSettingsResponse,
    ToolPermissionSettings,
    ToolPresetListResponse,
)
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api")


class AddRuleRequest(BaseModel):
    content: str


@router.get("/skills", response_model=SkillListResponse)
def list_skills() -> dict:
    return {
        "skills": [
            {
                "name": skill.name,
                "description": skill.description,
                "source": skill.source,
                "has_builtin": skill.has_builtin,
                "overrides_builtin": skill.overrides_builtin,
            }
            for skill in scan_skills()
        ]
    }


@router.get("/skills/{name}", response_model=SkillDetailResponse)
def get_skill_detail(name: str) -> dict:
    detail = read_skill_detail(name)
    if detail is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return detail


@router.post("/skills", response_model=SkillDetailResponse)
def create_skill(req: SkillUpsertRequest) -> dict:
    if not req.name:
        raise HTTPException(status_code=400, detail="Skill name is required")
    try:
        skill = create_custom_skill(req.name, req.content)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return read_skill_detail(skill.name) or {}


@router.put("/skills/{name}", response_model=SkillDetailResponse)
def update_skill(name: str, req: SkillUpsertRequest) -> dict:
    try:
        skill = upsert_custom_skill(name, req.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return read_skill_detail(skill.name) or {}


@router.delete("/skills/{name}")
def delete_skill(name: str) -> dict:
    try:
        delete_custom_skill(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"ok": True}


@router.post("/skills/{name}/restore-default", response_model=SkillDetailResponse)
def restore_skill_default(name: str) -> dict:
    try:
        restore_builtin_skill(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    detail = read_skill_detail(name)
    if detail is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return detail


@router.get("/tool-presets", response_model=ToolPresetListResponse)
def list_tool_presets() -> dict:
    return {
        "presets": [
            {"name": preset, "tools": preset.tool_names()}
            for preset in ToolSetPreset
            if preset != ToolSetPreset.CUSTOM
        ],
        "tools": [
            {"name": tool.name, "description": tool.description or ""}
            for tool in tool_registry.get_all()
        ],
    }


@router.get("/settings/session-defaults", response_model=SessionSettings)
def get_session_settings(
    settings_service: SettingsService = Depends(get_settings_service),
) -> dict:
    return settings_service.get_session_settings()


@router.put("/settings/session-defaults", response_model=SessionSettings)
def update_session_settings(
    req: SessionSettings,
    settings_service: SettingsService = Depends(get_settings_service),
) -> dict:
    return settings_service.update_session_settings(req)


@router.get("/settings/tool-permissions", response_model=ToolPermissionSettings)
def get_tool_permissions(
    settings_service: SettingsService = Depends(get_settings_service),
) -> dict:
    return settings_service.get_tool_permissions()


@router.put("/settings/tool-permissions", response_model=ToolPermissionSettings)
def update_tool_permissions(
    req: ToolPermissionSettings,
    settings_service: SettingsService = Depends(get_settings_service),
) -> dict:
    return settings_service.update_tool_permissions(req)


@router.get("/settings/sysguard", response_model=SysguardSettingsResponse)
def get_sysguard_settings(
    settings_service: SettingsService = Depends(get_settings_service),
) -> dict:
    return settings_service.get_sysguard_rules()


@router.post("/settings/sysguard/{scope}", response_model=SysguardSettingsResponse)
def add_sysguard_rule(
    scope: str,
    req: SysguardRuleRequest,
    settings_service: SettingsService = Depends(get_settings_service),
) -> dict:
    try:
        if scope not in {"global", "workspace"}:
            raise HTTPException(status_code=404, detail="Invalid sysguard scope")
        return settings_service.add_sysguard_rule(req, scope=scope)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.put("/settings/sysguard/{scope}/{rule_id}", response_model=SysguardSettingsResponse)
def update_sysguard_rule(
    scope: str,
    rule_id: str,
    req: SysguardRuleRequest,
    settings_service: SettingsService = Depends(get_settings_service),
) -> dict:
    try:
        if scope not in {"global", "workspace"}:
            raise HTTPException(status_code=404, detail="Invalid sysguard scope")
        return settings_service.update_sysguard_rule(rule_id, req, scope=scope)
    except KeyError:
        raise HTTPException(status_code=404, detail="Sysguard rule not found") from None
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.delete("/settings/sysguard/{scope}/{rule_id}", response_model=SysguardSettingsResponse)
def delete_sysguard_rule(
    scope: str,
    rule_id: str,
    settings_service: SettingsService = Depends(get_settings_service),
) -> dict:
    try:
        if scope not in {"global", "workspace"}:
            raise HTTPException(status_code=404, detail="Invalid sysguard scope")
        return settings_service.delete_sysguard_rule(rule_id, scope=scope)
    except KeyError:
        raise HTTPException(status_code=404, detail="Sysguard rule not found") from None


@router.post("/settings/session-rules", response_model=SessionSettings)
def add_session_rule(
    req: AddRuleRequest,
    settings_service: SettingsService = Depends(get_settings_service),
) -> dict:
    return settings_service.add_session_rule(req.content)


@router.delete("/settings/session-rules/{rule_id}", response_model=SessionSettings)
def delete_session_rule(
    rule_id: str,
    settings_service: SettingsService = Depends(get_settings_service),
) -> dict:
    return settings_service.delete_session_rule(rule_id)
