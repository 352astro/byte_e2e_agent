"""Write 工具 — 写入 workspace 文件。"""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class WriteInput(BaseModel):
    """Write 工具输入参数。"""

    path: str = Field(..., description="File path to write (relative to workspace).")
    content: str = Field(..., description="Text content to write to the file.")


async def write_handler(path: str, content: str, *, workspace=None) -> str:
    """Write text content to a file in the workspace."""
    return await workspace.write_file(path, content)


write_tool = StructuredTool.from_function(
    coroutine=write_handler,
    name="Write",
    description="Write text content to a file in the workspace.",
    args_schema=WriteInput,
)
