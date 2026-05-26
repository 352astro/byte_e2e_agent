"""
tools 包：工具定义和动态工具集。

工具已通过 ToolSet 实现动态联合类型分发，不再需要硬编码 Union。
Tool / SubTool 等旧式声明已移除。
"""

from agent.tools.base import BaseTool
from agent.tools.edit import Edit, EditOp
from agent.tools.read import Read
from agent.tools.search import Search
from agent.tools.shell import Shell
from agent.tools.skill import LoadSkill
from agent.tools.subagent import SubAgent
from agent.tools.task import Task, TaskList, TaskRewrite, TaskUpdate
from agent.tools.toolset import ToolSet
from agent.tools.write import Write

# ── 默认工具注册表 ──────────────────────────────────────

_ALL_TOOL_CLASSES: list[type[BaseTool]] = [
    Search,
    Shell,
    Read,
    Write,
    Edit,
    LoadSkill,
    SubAgent,
    TaskList,
    TaskRewrite,
    TaskUpdate,
]


def get_all_tool_classes() -> list[type[BaseTool]]:
    """返回默认全部工具类（供 ToolSet 初始化）。"""
    return list(_ALL_TOOL_CLASSES)


__all__ = [
    "BaseTool",
    "Edit",
    "EditOp",
    "LoadSkill",
    "Read",
    "Search",
    "Shell",
    "SubAgent",
    "Task",
    "TaskList",
    "TaskRewrite",
    "TaskUpdate",
    "ToolSet",
    "Write",
    "get_all_tool_classes",
]
