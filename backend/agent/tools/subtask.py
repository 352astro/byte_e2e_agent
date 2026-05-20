"""
SubTask 工具：启动子智能体执行独立任务。

SubTask 不走 execute()——由 ReActAgent 循环拦截，
使用受限工具集（无 SubTask）启动一个新的 ReActAgent。
"""

from typing import Literal

from pydantic import Field

from agent.tools.base import BaseTool


class SubTask(BaseTool):
    """
    以空上下文启动一个子智能体，使用受限工具集（禁止递归 SubTask）。

    子智能体完成后，其最终答案作为本工具的结果返回。
    """

    kind: Literal["SubTask"] = "SubTask"

    prompt: str = Field(
        ...,
        description="Task description for the subagent — treated as its question",
    )
    max_steps: int = Field(
        default=5,
        ge=1,
        le=15,
        description="Maximum reasoning steps for the subagent",
    )
