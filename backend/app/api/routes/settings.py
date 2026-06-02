from fastapi import APIRouter, Depends
from pydantic import BaseModel

from agent.tools.skill import scan_skills
from app.dependencies import get_settings_service
from app.schemas.session import SessionSettings, SkillListResponse
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api")


class AddRuleRequest(BaseModel):
    content: str


@router.get("/skills", response_model=SkillListResponse)
def list_skills() -> dict:
    return {
        "skills": [
            {"name": skill.name, "description": skill.description}
            for skill in scan_skills()
        ]
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
