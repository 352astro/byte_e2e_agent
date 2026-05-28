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
    prompt: str = Field(
        ...,
        description="Task description for the subagent — treated as its question",
    )
    fork: bool = Field(
        default=False,
        description=(
            "If True, the sub-agent inherits the full parent conversation "
            "history (all messages) and appends its own.  "
            "Useful when the sub-agent needs full context about what has "
            "been done so far."
        ),
    )

    async def execute(
        self,
        *,
        sandbox=None,
        channel=None,
        interrupt_event=None,
        scheduler=None,
        toolset=None,
        result_id: str = "",
    ) -> str:
        run = getattr(scheduler, "_run_subagent", None)
        if run is None:
            return "Error: SubAgent requires scheduler reference."
        return await run(
            sandbox,
            toolset,
            channel,
            self.prompt,
            self.max_steps,
            fork=self.fork,
        )
