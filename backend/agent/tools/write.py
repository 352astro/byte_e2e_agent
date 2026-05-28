"""Write 工具 — 委托 Sandbox 写入文件。"""

from pydantic import Field

from agent.tools.base import BaseTool


class Write(BaseTool):
    """Write text content to a file in the workspace."""

    path: str = Field(
        ...,
        description="File path to write (relative to workspace).",
    )
    content: str = Field(
        ...,
        description="Text content to write to the file.",
    )

    async def execute(self, *, sandbox=None, channel=None, interrupt_event=None, scheduler=None, toolset=None, result_id="") -> str:
        return await sandbox.write_file(self.path, self.content)
