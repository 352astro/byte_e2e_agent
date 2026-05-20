"""
Read 工具：安全读取工作目录内的文件。
"""

from typing import Literal

from pydantic import Field

from agent.tools._safety import safe_resolve_path
from agent.tools.base import BaseTool
from agent.tools.workspace import get_workspace_root


class Read(BaseTool):
    """
    读取文件内容并返回。

    路径相对于工作目录，且经过安全检查，无法读取工作目录之外的文件。
    """

    kind: Literal["Read"] = "Read"

    path: str = Field(
        ...,
        description="File path to read (relative to workspace). E.g. 'src/main.py' or 'README.md'",
    )

    def execute(self) -> str:
        """读取文件内容，返回文本。"""
        root = get_workspace_root()

        # 1. 路径安全检查
        try:
            safe_path = safe_resolve_path(self.path, root)
        except ValueError as exc:
            return f"Error: {exc}"

        # 2. 读取
        try:
            with open(safe_path, "r", encoding="utf-8") as fh:
                content = fh.read()
            return content if content else "(empty)"
        except FileNotFoundError:
            return f"Error: file not found '{self.path}'"
        except IsADirectoryError:
            return f"Error: '{self.path}' is a directory, not a file"
        except PermissionError:
            return f"Error: permission denied reading '{self.path}'"
        except UnicodeDecodeError:
            # 尝试二进制读取
            try:
                with open(safe_path, "rb") as fh:
                    content_bytes = fh.read()
                return (
                    f"[binary file, {len(content_bytes)} bytes, "
                    f"first 200 bytes preview]\n{content_bytes[:200]!r}"
                )
            except Exception as exc:
                return f"Error: cannot read binary file '{self.path}': {exc}"
        except Exception as exc:
            return f"Error: {exc}"
