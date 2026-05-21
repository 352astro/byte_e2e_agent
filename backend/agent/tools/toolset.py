"""
ToolSet — 动态工具集。

替代硬编码的 Tool / SubTool 联合类型。通过 Python 动态类型能力
在运行时生成 Pydantic discriminated union，支持按需排除工具（如子 agent 禁用 SubTask）。

用法:
    toolset = ToolSet([Finish, Shell, Read, Write, ...])
    adapter = toolset.adapter          # TypeAdapter — 用于 validate_json()
    schema  = toolset.json_schema      # dict — 注入 system prompt

    restricted = toolset.without(SubTask)  # 子 agent 用
"""

from __future__ import annotations

import json
from typing import Union

from pydantic import Field, TypeAdapter
from typing_extensions import Annotated

from agent.tools.base import BaseTool


class ToolSet:
    """一组工具的集合，可动态生成 Pydantic 鉴别联合类型。"""

    def __init__(self, tools: list[type[BaseTool]]) -> None:
        if not tools:
            raise ValueError("ToolSet must contain at least one tool.")
        self._tools: tuple[type[BaseTool], ...] = tuple(tools)
        self._adapter: TypeAdapter | None = None
        self._schema: dict | None = None

    # ── 属性 ──────────────────────────────────────────

    @property
    def tools(self) -> tuple[type[BaseTool], ...]:
        return self._tools

    @property
    def adapter(self) -> TypeAdapter:
        """返回可校验任意一个工具 JSON 的 TypeAdapter。"""
        if self._adapter is None:
            union = Union[self._tools]  # type: ignore[valid-type]
            self._adapter = TypeAdapter(Annotated[union, Field(discriminator="kind")])
        return self._adapter

    @property
    def json_schema(self) -> dict:
        """返回工具联合类型的 JSON Schema（用于注入 system prompt）。"""
        if self._schema is None:
            self._schema = self.adapter.json_schema()
        return self._schema

    @property
    def json_schema_str(self) -> str:
        """返回格式化的 JSON Schema 字符串。"""
        return json.dumps(self.json_schema, indent=2, ensure_ascii=False)

    # ── 工具集操作 ────────────────────────────────────

    def without(self, *exclude: type[BaseTool]) -> "ToolSet":
        """返回一个新 ToolSet，排除指定工具。"""
        return ToolSet([t for t in self._tools if t not in exclude])

    def __contains__(self, tool_cls: type[BaseTool]) -> bool:
        return tool_cls in self._tools

    def __repr__(self) -> str:
        names = [t.__name__ for t in self._tools]
        return f"ToolSet({', '.join(names)})"
