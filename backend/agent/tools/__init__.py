"""tools 包 — 工具定义和注册表。

所有工具以 LangChain StructuredTool 形式注册到全局 ToolRegistry。
ToolSet 从 registry 构建子集。
"""

from agent.tools.browser import (
    browser_act_tool,
    browser_inspect_tool,
    browser_open_tool,
)
from agent.tools.edit import edit_tool
from agent.tools.glob import glob_tool
from agent.tools.grep import grep_tool
from agent.tools.listdir import listdir_tool
from agent.tools.pyrepl import pyrepl_tool
from agent.tools.read import read_tool
from agent.tools.registry import ToolRegistry
from agent.tools.search import web_fetch_tool, web_search_tool
from agent.tools.shell import shell_tool
from agent.tools.skill import load_skill_tool
from agent.tools.subagent import subagent_tool
from agent.tools.task import task_list_tool, task_rewrite_tool, task_update_tool
from agent.tools.toolset import ToolSet
from agent.tools.write import write_tool

# ── 全局注册表 ─────────────────────────────────────────

tool_registry = ToolRegistry()

# 注册所有工具（按名称）
tool_registry.register(shell_tool)
tool_registry.register(read_tool)
tool_registry.register(write_tool)
tool_registry.register(edit_tool)
tool_registry.register(glob_tool)
tool_registry.register(grep_tool)
tool_registry.register(listdir_tool)
tool_registry.register(pyrepl_tool)
tool_registry.register(web_search_tool)
tool_registry.register(web_fetch_tool)
tool_registry.register(load_skill_tool)
tool_registry.register(subagent_tool)
tool_registry.register(browser_open_tool)
tool_registry.register(browser_act_tool)
tool_registry.register(browser_inspect_tool)
tool_registry.register(task_list_tool)
tool_registry.register(task_rewrite_tool)
tool_registry.register(task_update_tool)


def _default_toolset() -> ToolSet:
    """创建默认 ToolSet（包含所有工具）。"""
    return ToolSet(tool_registry)


__all__ = [
    "ToolRegistry",
    "ToolSet",
    "tool_registry",
    "_default_toolset",
]
