"""Read 工具 — 委托 SandBox 读取文件。"""


from pydantic import Field

from agent.tools.base import BaseTool


class Read(BaseTool):

    path: str = Field(
        ...,
        description="File path to read (relative to workspace).",
    )

    async def execute(self, sandbox=None) -> str:
        return await sandbox.read_file(self.path)
