"""SubAgent 工具：启动子智能体执行独立任务。"""

from pydantic import Field

from agent.tools.base import BaseTool


class SubAgent(BaseTool):
    """Launch a sub-agent with a restricted toolset (no recursive SubAgent)."""

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

    async def execute(
        self,
        *,
        sandbox=None,
        channel=None,
        interrupt_event=None,
        toolset=None,
        result_id: str = "",
        llm_client=None,
    ) -> str:
        from agent.actions import run_subagent

        return await run_subagent(
            sandbox,
            toolset,
            channel,
            self.prompt,
            self.max_steps,
            llm_client=llm_client,
            session_id="",
            interrupt_event=interrupt_event,
            with_skills=self.with_skills,
        )
