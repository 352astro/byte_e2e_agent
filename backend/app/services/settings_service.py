"""Workspace settings used when creating user sessions."""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.schemas.session import SessionRule, SessionSettings
from app.services.context import WorkspaceContext

SESSION_DEFAULTS_FILE = "session_defaults.json"


class SettingsService:
    def __init__(self, ctx: WorkspaceContext) -> None:
        self._ctx = ctx

    def get_session_settings(self) -> dict[str, Any]:
        return _load_settings(self._ctx).model_dump()

    def update_session_settings(self, settings: SessionSettings) -> dict[str, Any]:
        cleaned = _clean_settings(settings)
        _write_settings(self._ctx, cleaned)
        return cleaned.model_dump()

    def add_session_rule(self, content: str) -> dict[str, Any]:
        settings = _load_settings(self._ctx)
        trimmed = content.strip()
        if not trimmed:
            return settings.model_dump()
        settings.rules.append(SessionRule(id=uuid.uuid4().hex[:12], content=trimmed))
        cleaned = _clean_settings(settings)
        _write_settings(self._ctx, cleaned)
        return cleaned.model_dump()

    def delete_session_rule(self, rule_id: str) -> dict[str, Any]:
        settings = _load_settings(self._ctx)
        settings.rules = [rule for rule in settings.rules if rule.id != rule_id]
        settings.default_rule_ids = [
            item for item in settings.default_rule_ids if item != rule_id
        ]
        cleaned = _clean_settings(settings)
        _write_settings(self._ctx, cleaned)
        return cleaned.model_dump()


def _load_settings(ctx: WorkspaceContext) -> SessionSettings:
    path = ctx.core_workspace.agent_dir() / SESSION_DEFAULTS_FILE
    if not path.is_file():
        return SessionSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return SessionSettings()
    if not isinstance(data, dict):
        return SessionSettings()
    return _clean_settings(SessionSettings(**data))


def _write_settings(ctx: WorkspaceContext, settings: SessionSettings) -> None:
    path = ctx.core_workspace.agent_dir() / SESSION_DEFAULTS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings.model_dump(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _clean_settings(settings: SessionSettings) -> SessionSettings:
    rules: list[SessionRule] = []
    seen_rule_ids: set[str] = set()
    for rule in settings.rules:
        rule_id = rule.id.strip()
        content = rule.content.strip()
        if not rule_id or not content or rule_id in seen_rule_ids:
            continue
        seen_rule_ids.add(rule_id)
        rules.append(SessionRule(id=rule_id, content=content))

    return SessionSettings(
        preamble=settings.preamble.strip(),
        rules=rules,
        default_rule_ids=[
            item.strip()
            for item in settings.default_rule_ids
            if item.strip() in seen_rule_ids
        ],
        default_skill_names=[
            item.strip() for item in settings.default_skill_names if item.strip()
        ],
    )
