"""
tools 包：基于 Pydantic 鉴别联合（discriminated union）的工具系统。

所有工具通过 Tool / SubTool 联合类型统一管理，通过 kind 字段自动分发。
- Tool:    顶层 agent 可用全部工具（含 SubTask）
- SubTool: 子 agent 可用工具（不含 SubTask，防止递归）
"""

from typing import Annotated, Any, Dict, Union

from pydantic import Field

from agent.tools.base import BaseTool
from agent.tools.edit import Edit, EditOp
from agent.tools.finish import Finish
from agent.tools.plan import PlanAdvance, PlanItem, PlanRewrite
from agent.tools.read import Read
from agent.tools.search import Search
from agent.tools.shell import Shell
from agent.tools.subtask import SubTask
from agent.tools.workspace import get_workspace_root, set_workspace_root
from agent.tools.write import Write

# ============================================================
# 工具联合类型
# ============================================================

# 顶层 agent：全部工具
Tool = Annotated[
    Union[Finish, Search, Shell, Read, Write, Edit, PlanRewrite, PlanAdvance, SubTask],
    Field(discriminator="kind"),
]

# 子 agent：排除 SubTask（禁止递归）
SubTool = Annotated[
    Union[Finish, Search, Shell, Read, Write, Edit, PlanRewrite, PlanAdvance],
    Field(discriminator="kind"),
]

# ============================================================
# 工具类列表
# ============================================================

_ALL_TOOL_CLASSES: list[type[BaseTool]] = [
    Finish,
    Search,
    Shell,
    Read,
    Write,
    Edit,
    PlanRewrite,
    PlanAdvance,
    SubTask,
]

_SUB_TOOL_CLASSES: list[type[BaseTool]] = [
    Finish,
    Search,
    Shell,
    Read,
    Write,
    Edit,
    PlanRewrite,
    PlanAdvance,
]

# ============================================================
# 公共函数
# ============================================================


def get_all_tool_classes() -> list[type[BaseTool]]:
    """返回顶层 agent 的全部工具类（含 SubTask）。"""
    return list(_ALL_TOOL_CLASSES)


def get_sub_tool_classes() -> list[type[BaseTool]]:
    """返回子 agent 的工具类（不含 SubTask）。"""
    return list(_SUB_TOOL_CLASSES)


def get_executable_tool_classes() -> list[type[BaseTool]]:
    """返回可执行工具类（不含 Finish 等信号工具）。"""
    return [cls for cls in _ALL_TOOL_CLASSES if cls.__name__ != "Finish"]


def get_tool_schemas() -> Dict[str, Dict[str, Any]]:
    """返回顶层全部工具的 JSON Schema（{类名: schema}）。"""
    return _build_schemas(_ALL_TOOL_CLASSES)


def get_sub_tool_schemas() -> Dict[str, Dict[str, Any]]:
    """返回子 agent 工具的 JSON Schema（不含 SubTask）。"""
    return _build_schemas(_SUB_TOOL_CLASSES)


def get_tool_schemas_for(
    tool_classes: list[type[BaseTool]],
) -> Dict[str, Dict[str, Any]]:
    """根据给定工具类列表返回 JSON Schema。"""
    return _build_schemas(tool_classes)


def get_tool_class_by_kind(kind: str) -> type[BaseTool] | None:
    """根据 kind 字符串查找对应的工具类。"""
    for cls in _ALL_TOOL_CLASSES:
        if cls.model_fields["kind"].default == kind:
            return cls
    return None


def _build_schemas(
    tool_classes: list[type[BaseTool]],
) -> Dict[str, Dict[str, Any]]:
    return {cls.__name__: cls.model_json_schema() for cls in tool_classes}


__all__ = [
    "BaseTool",
    "Edit",
    "EditOp",
    "Finish",
    "PlanAdvance",
    "PlanItem",
    "PlanRewrite",
    "Read",
    "Search",
    "Shell",
    "SubTask",
    "Write",
    "Tool",
    "SubTool",
    "get_all_tool_classes",
    "get_sub_tool_classes",
    "get_executable_tool_classes",
    "get_tool_schemas",
    "get_sub_tool_schemas",
    "get_tool_schemas_for",
    "get_tool_class_by_kind",
    "get_workspace_root",
    "set_workspace_root",
]
