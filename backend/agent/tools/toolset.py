"""
ToolSet — 动态工具集，为 OpenAI 原生 function calling 服务。

替代旧的 Pydantic discriminated union 方案。
每个工具生成一个 OpenAI function definition，
通过函数名分发反序列化。

用法:
    ts = ToolSet([Shell, Read, Write, ...])
    ts.openai_tools            # → list[dict] 传给 API
    ts.parse(name, arguments)  # → BaseTool 实例
    ts.without(SubTask)        # → 新 ToolSet
"""

from __future__ import annotations

from agent.tools.base import BaseTool

# ── Pydantic schema → OpenAI parameters ────────────────────

_SKIP_TOP = frozenset({"title", "description", "$defs", "$schema"})


def _strip_pydantic_noise(schema: dict) -> dict:
    """递归去掉 Pydantic JSON Schema 中 OpenAI 不需要的顶层字段。"""
    if isinstance(schema, dict):
        return {
            k: _strip_pydantic_noise(v) for k, v in schema.items() if k not in _SKIP_TOP
        }
    if isinstance(schema, list):
        return [_strip_pydantic_noise(i) for i in schema]
    return schema


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


def _build_function_def(cls: type[BaseTool]) -> dict:
    """从 Pydantic 工具类生成单个 OpenAI function definition。"""
    raw = cls.model_json_schema()
    # 去掉 kind 字段（函数名已承担分发职责）
    if "properties" in raw and "kind" in raw["properties"]:
        del raw["properties"]["kind"]
    if "required" in raw:
        raw["required"] = [r for r in raw["required"] if r != "kind"]
    params = _ensure_strict(_strip_pydantic_noise(raw))
    return {
        "type": "function",
        "function": {
            "name": cls.function_name(),
            "description": (cls.__doc__ or "").strip().split("\n")[0],
            "parameters": params,
        },
    }


# ── ToolSet ────────────────────────────────────────────────


class ToolSet:
    """按名称注册工具的集合，生成 OpenAI function 列表。"""

    def __init__(self, tools: list[type[BaseTool]]) -> None:
        if not tools:
            raise ValueError("ToolSet must contain at least one tool.")
        self._tools: tuple[type[BaseTool], ...] = tuple(tools)
        self._registry: dict[str, type[BaseTool]] = {
            t.function_name(): t for t in tools
        }

    # ── 属性 ──────────────────────────────────────────

    @property
    def tools(self) -> tuple[type[BaseTool], ...]:
        return self._tools

    @property
    def openai_tools(self) -> list[dict]:
        """生成 OpenAI / DeepSeek tools 参数列表。"""
        return [_build_function_def(t) for t in self._tools]

    # ── 工具操作 ──────────────────────────────────────

    def parse(self, name: str, arguments: str) -> BaseTool:
        """根据函数名和 JSON arguments 反序列化为工具实例。"""
        cls = self._registry.get(name)
        if cls is None:
            raise KeyError(f"Unknown tool: {name}. Available: {list(self._registry)}")
        return cls.model_validate_json(arguments)

    def without(self, *exclude: type[BaseTool]) -> "ToolSet":
        """返回排除指定工具的新 ToolSet。"""
        return ToolSet([t for t in self._tools if t not in exclude])

    def __contains__(self, tool_cls: type[BaseTool]) -> bool:
        return tool_cls in self._tools

    def __repr__(self) -> str:
        names = [t.__name__ for t in self._tools]
        return f"ToolSet({', '.join(names)})"
