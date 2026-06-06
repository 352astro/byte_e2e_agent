"""Workspace settings used when creating user sessions."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from agent.tools import tool_registry
from app.schemas.session import (
    SessionRule,
    SessionSettings,
    SysguardRuleRequest,
    ToolPermissionSettings,
)
from app.services.context import WorkspaceContext

SESSION_DEFAULTS_FILE = "session_defaults.json"
TOOL_PERMISSIONS_FILE = "tool_permissions.json"
SYSGUARD_ALLOWLIST_FILE = "sysguard_allowlist.json"
_PERMISSION_VALUES = {"allow", "ask", "deny"}
_SYSGUARD_RULE_MODES = {"readonly", "readonly_exec", "readwrite"}
_SYSGUARD_MODE_LEVEL = {"readonly": 1, "readonly_exec": 2, "readwrite": 3}


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

    def get_tool_permissions(self) -> dict[str, Any]:
        return _load_tool_permissions(self._ctx).model_dump()

    def update_tool_permissions(
        self, settings: ToolPermissionSettings
    ) -> dict[str, Any]:
        cleaned = _clean_tool_permissions(settings)
        _write_tool_permissions(self._ctx, cleaned)
        return cleaned.model_dump()

    def get_sysguard_rules(self) -> dict[str, Any]:
        return load_sysguard_rules()

    def add_sysguard_rule(self, req: SysguardRuleRequest) -> dict[str, Any]:
        data = load_sysguard_rules()
        custom = data["custom"]
        rule = _clean_sysguard_rule(
            {
                "id": uuid.uuid4().hex[:12],
                "label": req.label,
                "path": req.path,
                "enabled": req.enabled,
                "description": req.description,
                "source": "custom",
                "mode": req.mode,
            }
        )
        _ensure_unique_custom_rule(custom, rule["path"])
        custom.append(rule)
        _write_sysguard_rules(custom)
        return load_sysguard_rules()

    def update_sysguard_rule(
        self, rule_id: str, req: SysguardRuleRequest
    ) -> dict[str, Any]:
        data = load_sysguard_rules()
        custom = data["custom"]
        updated = _clean_sysguard_rule(
            {
                "id": rule_id,
                "label": req.label,
                "path": req.path,
                "enabled": req.enabled,
                "description": req.description,
                "source": "custom",
                "mode": req.mode,
            }
        )
        found = False
        next_custom: list[dict[str, Any]] = []
        for rule in custom:
            if rule["id"] == rule_id:
                found = True
                next_custom.append(updated)
            else:
                next_custom.append(rule)
        if not found:
            raise KeyError(rule_id)
        _ensure_unique_custom_rule(next_custom, updated["path"], ignore_id=rule_id)
        _write_sysguard_rules(next_custom)
        return load_sysguard_rules()

    def delete_sysguard_rule(self, rule_id: str) -> dict[str, Any]:
        data = load_sysguard_rules()
        custom = [rule for rule in data["custom"] if rule["id"] != rule_id]
        if len(custom) == len(data["custom"]):
            raise KeyError(rule_id)
        _write_sysguard_rules(custom)
        return load_sysguard_rules()


def _config_path(filename: str) -> Path:
    from app.core.config import AGENT_DATA_DIR, PROJECT_ROOT

    return PROJECT_ROOT / AGENT_DATA_DIR / filename


def load_sysguard_rules() -> dict[str, Any]:
    from agent.utils.sysguard import list_builtin_rules

    custom = _load_custom_sysguard_rules()
    return {
        "builtin": [rule.__dict__ for rule in list_builtin_rules()],
        "custom": custom,
    }


def add_custom_sysguard_rule(
    *,
    label: str,
    path: str,
    mode: str = "readonly_exec",
    description: str = "",
    enabled: bool = True,
) -> dict[str, Any]:
    custom = _load_custom_sysguard_rules()
    rule = _clean_sysguard_rule(
        {
            "id": uuid.uuid4().hex[:12],
            "label": label,
            "path": path,
            "enabled": enabled,
            "description": description,
            "source": "custom",
            "mode": mode,
        }
    )
    custom = _merge_or_add_sysguard_rule(custom, rule)
    _write_sysguard_rules(custom)
    return rule


def _load_settings(ctx: WorkspaceContext) -> SessionSettings:
    path = _config_path(SESSION_DEFAULTS_FILE)
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
    path = _config_path(SESSION_DEFAULTS_FILE)
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


def _load_tool_permissions(ctx: WorkspaceContext) -> ToolPermissionSettings:
    path = _config_path(TOOL_PERMISSIONS_FILE)
    if not path.is_file():
        return ToolPermissionSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ToolPermissionSettings()
    if not isinstance(data, dict):
        return ToolPermissionSettings()
    return _clean_tool_permissions(ToolPermissionSettings(**data))


def _write_tool_permissions(
    ctx: WorkspaceContext, settings: ToolPermissionSettings
) -> None:
    path = _config_path(TOOL_PERMISSIONS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings.model_dump(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _clean_tool_permissions(
    settings: ToolPermissionSettings,
) -> ToolPermissionSettings:
    known = set(tool_registry.tool_names)
    tools: dict[str, str] = {}
    for name, mode in settings.tools.items():
        clean_name = name.strip()
        clean_mode = str(mode).strip()
        if clean_name not in known or clean_mode not in _PERMISSION_VALUES:
            continue
        tools[clean_name] = clean_mode
    return ToolPermissionSettings(tools=tools)


def _load_custom_sysguard_rules() -> list[dict[str, Any]]:
    path = _config_path(SYSGUARD_ALLOWLIST_FILE)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, dict):
        return []
    raw_custom = data.get("custom", [])
    if not isinstance(raw_custom, list):
        return []
    rules: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for item in raw_custom:
        if not isinstance(item, dict):
            continue
        try:
            rule = _clean_sysguard_rule(item)
        except ValueError:
            continue
        if rule["path"] in seen_paths:
            continue
        seen_paths.add(rule["path"])
        rules.append(rule)
    return rules


def _write_sysguard_rules(custom: list[dict[str, Any]]) -> None:
    path = _config_path(SYSGUARD_ALLOWLIST_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"custom": [_clean_sysguard_rule(rule) for rule in custom]}
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _clean_sysguard_rule(rule: dict[str, Any]) -> dict[str, Any]:
    rule_id = str(rule.get("id", "")).strip()
    label = str(rule.get("label", "")).strip()
    raw_path = str(rule.get("path", "")).strip()
    mode = str(rule.get("mode", "readonly_exec")).strip()
    description = str(rule.get("description", "")).strip()
    if not rule_id:
        raise ValueError("rule id is required")
    if not label:
        raise ValueError("rule label is required")
    if not raw_path:
        raise ValueError("rule path is required")
    if mode not in _SYSGUARD_RULE_MODES:
        raise ValueError(f"invalid sysguard rule mode: {mode}")
    resolved = Path(raw_path).expanduser().resolve()
    if not resolved.exists():
        raise ValueError(f"path does not exist: {raw_path}")
    if _overlaps_project_root(resolved):
        raise ValueError(
            "Sysguard allowlist path cannot be the application repository, "
            f"contain it, or be inside it: {resolved}"
        )
    return {
        "id": rule_id,
        "label": label,
        "path": str(resolved),
        "mode": mode,
        "source": "custom",
        "enabled": bool(rule.get("enabled", True)),
        "description": description,
    }


def _ensure_unique_custom_rule(
    rules: list[dict[str, Any]], path: str, *, ignore_id: str = ""
) -> None:
    for rule in rules:
        if ignore_id and rule.get("id") == ignore_id:
            continue
        if rule.get("path") == path:
            raise FileExistsError(f"Sysguard rule already exists for path: {path}")


def _merge_or_add_sysguard_rule(
    rules: list[dict[str, Any]], new_rule: dict[str, Any]
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    found = False
    for rule in rules:
        if rule.get("path") != new_rule["path"]:
            merged.append(rule)
            continue
        found = True
        existing_mode = str(rule.get("mode", "readonly_exec"))
        new_mode = str(new_rule.get("mode", "readonly_exec"))
        mode = (
            new_mode
            if _SYSGUARD_MODE_LEVEL[new_mode] > _SYSGUARD_MODE_LEVEL[existing_mode]
            else existing_mode
        )
        merged.append(
            {
                **rule,
                "mode": mode,
                "enabled": True,
                "description": rule.get("description") or new_rule.get("description", ""),
            }
        )
    if not found:
        merged.append(new_rule)
    return merged


def _overlaps_project_root(path: Path) -> bool:
    from app.core.config import PROJECT_ROOT

    project_root = PROJECT_ROOT.resolve()
    try:
        path.relative_to(project_root)
        return True
    except ValueError:
        pass
    try:
        project_root.relative_to(path)
        return True
    except ValueError:
        return False
