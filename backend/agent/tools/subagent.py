"""SubAgent 工具：启动子智能体执行独立任务。

实际执行由 agent.tool_execution.execute_one_tool 原地分发，
本模块仅承载参数定义和 OpenAI schema 生成。
"""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class SubAgentInput(BaseModel):
    """SubAgent 工具输入参数。"""

    max_steps: int = Field(
        default=5,
        ge=1,
        le=15,
        description="Maximum reasoning steps for the subagent",
    )
    with_skills: list[str] = Field(
        default_factory=list,
        description=(
            "Skill names to load and inject into the sub-agent's context "
            "before it starts. Each skill's full content is inserted as a "
            "system message, so the sub-agent follows its methodology "
            "without needing to call LoadSkill itself."
        ),
    )
    prompt: str = Field(
        ...,
        description=(
            "Task description for the sub-agent — treated as its question.\n"
            "\n"
            "CRITICAL: the sub-agent starts with an EMPTY context — it sees "
            "nothing from the parent conversation. You MUST embed ALL relevant "
            "information into this prompt: what has been done so far, current "
            "state, file paths, error messages, decisions made, constraints, "
            "and exactly what to do. A vague one-liner will cause the sub-agent "
            "to fail. Be exhaustive."
        ),
    )


async def subagent_handler(**kwargs) -> str:
    """实际执行在 execute_one_tool 中通过名称分发。"""
    return "Error: SubAgent must be dispatched via execute_one_tool."


subagent_tool = StructuredTool.from_function(
    coroutine=subagent_handler,
    name="SubAgent",
    description="Launch a sub-agent with a restricted toolset (no recursive SubAgent).",
    args_schema=SubAgentInput,
)
