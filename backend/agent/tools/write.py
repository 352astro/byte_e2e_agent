"""
Write 工具：安全写入文件到工作目录内。
"""

import os
from typing import Literal

from pydantic import Field

from agent.tools._safety import safe_resolve_path
from agent.tools.base import BaseTool
from agent.tools.workspace import get_workspace_root


class Write(BaseTool):
    """
    将内容写入文件（自动创建父目录）。

    路径相对于工作目录，且经过安全检查，无法写入工作目录之外的文件。
    """

    kind: Literal["Write"] = "Write"

    path: str = Field(
        ...,
        description="File path to write (relative to workspace). E.g. 'output/result.txt'",
    )
    content: str = Field(
        ...,
        description="Text content to write to the file",
    )

    def execute(self) -> str:
        """写入文件并返回确认信息。"""
        root = get_workspace_root()

        # 1. 路径安全检查
        try:
            safe_path = safe_resolve_path(self.path, root)
        except ValueError as exc:
            return f"Error: {exc}"

        # 2. 写入
        try:
            # 自动创建父目录
            parent = os.path.dirname(safe_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            with open(safe_path, "w", encoding="utf-8") as fh:
                fh.write(self.content)

            return f"Successfully wrote {self.path} ({len(self.content)} characters)"

        except PermissionError:
            return f"Error: permission denied writing '{self.path}'"
        except IsADirectoryError:
            return (
                f"Error: '{self.path}' is an existing directory, cannot write as file"
            )
        except Exception as exc:
            return f"Error: {exc}"
