"""
ToolSet — 工具集，为 OpenAI function calling 服务。

适配 LangChain StructuredTool 注册方式。
每个工具注册到 ToolRegistry，ToolSet 从 registry 构建子集。

用法:
    ts = ToolSet(registry)           # 全部工具
    ts = ToolSet(registry, "Shell", "Read", "Write")  # 子集
    ts.openai_tools                   # → list[dict] 传给 API
    ts.parse(name, arguments)         # → (StructuredTool, parsed_args_dict)
    ts.without("SubAgent")            # → 新 ToolSet
"""

from __future__ import annotations

import json

from langchain_core.tools import StructuredTool

from agent.tools.registry import ToolRegistry


class ToolSet:
    """按名称过滤的工具子集。"""

    def __init__(
        self,
        registry: ToolRegistry,
        *names: str,
    ) -> None:
        if names:
            self._tools: dict[str, StructuredTool] = {}
            for name in names:
                tool = registry.get(name)
                if tool is None:
                    raise KeyError(f"Unknown tool: {name}")
                self._tools[name] = tool
        else:
            # 全部工具
            self._tools = {t.name: t for t in registry.get_all()}

        if not self._tools:
            raise ValueError("ToolSet must contain at least one tool.")

    # ── 属性 ──────────────────────────────────────────

    @property
    def tools(self) -> list[StructuredTool]:
        return list(self._tools.values())

    @property
    def openai_tools(self) -> list[dict]:
        """生成 OpenAI / DeepSeek tools 参数列表。"""
        from agent.tools.registry import _tool_to_openai

        return [_tool_to_openai(t) for t in self._tools.values()]

    # ── 工具操作 ──────────────────────────────────────

    def parse(self, name: str, arguments: str) -> tuple[StructuredTool, dict]:
        """根据函数名和 JSON arguments 解析工具和参数。

        Returns:
            (StructuredTool, parsed_args_dict)
        """
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Unknown tool: {name}. Available: {list(self._tools)}")
        try:
            args = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON arguments for {name}: {exc}") from exc
        return tool, args

    def without(self, *names: str) -> ToolSet:
        """返回排除指定工具的新 ToolSet。"""
        result = ToolSet.__new__(ToolSet)
        result._tools = {name: tool for name, tool in self._tools.items() if name not in names}
        if not result._tools:
            raise ValueError(f"ToolSet would be empty after excluding {names}")
        return result

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __repr__(self) -> str:
        return f"ToolSet({', '.join(self._tools.keys())})"
