"""BaseTool — 所有工具的基类。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from agent.llm import HelloAgentsLLM
    from agent.sandbox import Sandbox as _Sandbox
    from agent.tools.toolset import ToolSet as _ToolSet
    from agent.transcript import TranscriptStream


class BaseTool(BaseModel):
    """所有工具的基类。

    子类重写 execute()，按需使用传入的参数。
    """

    @classmethod
    def function_name(cls) -> str:
        """OpenAI function 名称（默认使用类名，如 Shell、Read、Write）。"""
        return cls.__name__

    async def execute(
        self,
        *,
        sandbox: _Sandbox | None = None,
        channel: TranscriptStream | None = None,
        interrupt_event: asyncio.Event | None = None,
        toolset: _ToolSet | None = None,
        result_id: str = "",
    ) -> str:
        raise NotImplementedError(f"{type(self).__name__} 未实现 execute()")
