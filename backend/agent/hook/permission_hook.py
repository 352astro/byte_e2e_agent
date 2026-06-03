"""Global tool permission guard."""

from __future__ import annotations

import json

from shared.hooks import BaseHook, GuardCheck, GuardDecision

TOOL_PERMISSIONS_FILE = "tool_permissions.json"


class ToolPermissionHook(BaseHook):
    """Read global tool permissions from PROJECT_ROOT/.agent/."""

    def __init__(self, workspace: str) -> None:
        from app.core.config import PROJECT_ROOT

        self._permissions_path = PROJECT_ROOT / ".agent" / TOOL_PERMISSIONS_FILE

    async def on_guard_check(
        self,
        *,
        check: GuardCheck,
        **kwargs,
    ) -> GuardDecision | None:
        if check.action_type != "tool.execute":
            return None
        mode = self._load().get(check.subject, "allow")
        if mode == "deny":
            return GuardDecision.DENY
        if mode == "ask":
            return GuardDecision.ASK
        return GuardDecision.ALLOW

    def _load(self) -> dict[str, str]:
        path = self._permissions_path
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(data, dict):
            return {}
        tools = data.get("tools", {})
        if not isinstance(tools, dict):
            return {}
        result: dict[str, str] = {}
        for name, mode in tools.items():
            if isinstance(name, str) and mode in {"allow", "ask", "deny"}:
                result[name] = str(mode)
        return result
