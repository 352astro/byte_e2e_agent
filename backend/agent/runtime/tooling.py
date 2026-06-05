"""Runtime toolset helpers."""

from __future__ import annotations

from agent.tools import tool_registry
from agent.tools.toolset import ToolSet


def default_toolset() -> ToolSet:
    return ToolSet(tool_registry)


def entry_id(entry) -> str:
    value = getattr(entry, "id", "")
    if isinstance(value, str) and value:
        return value
    legacy_value = getattr(entry, "session_id", "")
    if isinstance(legacy_value, str) and legacy_value:
        return legacy_value
    return str(value)
