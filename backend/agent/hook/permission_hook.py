"""Global tool permission guard."""

from __future__ import annotations

import json
from pathlib import Path

from shared.hooks import BaseHook, GuardCheck, GuardDecision

TOOL_PERMISSIONS_FILE = "tool_permissions.json"


class ToolPermissionHook(BaseHook):
    """Read workspace-level tool permissions before tool execution."""

    def __init__(self, workspace: str) -> None:
        self._workspace = Path(workspace)

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
        path = self._workspace / ".byte_agent" / TOOL_PERMISSIONS_FILE
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
