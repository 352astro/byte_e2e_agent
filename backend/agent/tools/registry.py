"""ToolRegistry — LangChain StructuredTool 注册表。

── 设计 ──
- 所有工具以 LangChain StructuredTool 形式注册（生态兼容）
- OpenAI function definitions 从 StructuredTool.args_schema 生成
- 执行分发仍由 execute_one_tool 掌控（SubAgent/BrowserInspect 特殊处理）
- Workspace 在执行时通过 handler 的 workspace= 关键字注入
"""

from __future__ import annotations

from copy import deepcopy

from langchain_core.tools import StructuredTool

# ── OpenAI schema 生成 ──────────────────────────────────

_SKIP_META = frozenset({"title", "$defs", "$schema"})


def _strip_pydantic_noise(schema: dict, *, in_properties: bool = False) -> dict:
    """递归去掉 Pydantic JSON Schema 中 OpenAI 不需要的顶层字段。"""
    if isinstance(schema, dict):
        result = {}
        for k, v in schema.items():
            if not in_properties and k in _SKIP_META:
                continue
            result[k] = _strip_pydantic_noise(v, in_properties=(k == "properties"))
        return result
    if isinstance(schema, list):
        return [_strip_pydantic_noise(i) for i in schema]
    return schema


def _inline_refs(schema: dict) -> dict:
    """Inline local $defs refs so OpenAI receives concrete nested object schemas."""
    defs = schema.get("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.removeprefix("#/$defs/")
                target = deepcopy(defs.get(name, {}))
                extras = {k: v for k, v in node.items() if k != "$ref"}
                target.update(extras)
                return resolve(target)
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


def _ensure_strict(schema: dict) -> dict:
    """为所有 object 节点添加 required 和 additionalProperties: false（strict 模式）。"""
    if schema.get("type") == "object" and "properties" in schema:
        props = schema["properties"]
        if isinstance(props, dict) and props:
            schema["required"] = list(props.keys())
        schema["additionalProperties"] = False
    for v in schema.values():
        if isinstance(v, dict):
            _ensure_strict(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    _ensure_strict(item)
    return schema


def _tool_to_openai(tool: StructuredTool) -> dict:
    """从 StructuredTool 生成 OpenAI function definition。"""
    raw = _inline_refs(tool.args_schema.model_json_schema())
    params = _ensure_strict(_strip_pydantic_noise(raw))
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": (tool.description or "").strip(),
            "parameters": params,
            "strict": True,
        },
    }


# ── ToolRegistry ────────────────────────────────────────


class ToolRegistry:
    """按名称注册 StructuredTool 的集合。

    用法:
        registry = ToolRegistry()
        registry.register(shell_tool)
        registry.register(read_tool)
        tools = registry.openai_tools()  # → list[dict] 传给 LLM
        tool = registry.get("Shell")     # → StructuredTool
    """

    def __init__(self) -> None:
        self._tools: dict[str, StructuredTool] = {}

    def register(self, tool: StructuredTool) -> None:
        """注册一个工具。同名工具会覆盖。"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> StructuredTool | None:
        return self._tools.get(name)

    def get_all(self) -> list[StructuredTool]:
        return list(self._tools.values())

    def openai_tools(self) -> list[dict]:
        """生成 OpenAI / DeepSeek tools 参数列表。"""
        return [_tool_to_openai(t) for t in self._tools.values()]

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __repr__(self) -> str:
        return f"ToolRegistry({', '.join(self._tools.keys())})"
