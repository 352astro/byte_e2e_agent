"""
Edit 工具：对现有文件进行精确的逐块查找替换。
"""

from typing import Literal

from pydantic import BaseModel, Field

from agent.tools._safety import safe_resolve_path
from agent.tools.base import BaseTool
from agent.tools.workspace import get_workspace_root

# ============================================================
# 编辑操作
# ============================================================


class EditOp(BaseModel):
    """
    单次编辑操作：在文件中查找 old_text，替换为 new_text。

    匹配规则：
    1. 先尝试精确匹配
    2. 精确匹配失败则尝试规范化空白符后逐行匹配
    """

    old_text: str = Field(
        ...,
        description="Exact text to find in the file (used as search anchor)",
    )
    new_text: str = Field(
        ...,
        description="Replacement text to substitute in place of old_text",
    )


# ============================================================
# Edit 工具
# ============================================================


class Edit(BaseTool):
    """
    对工作目录内的现有文件执行一系列有序的查找替换操作。

    每次编辑在上一次的结果上叠加；若某次查找失败则中止并报错。
    如需创建新文件请使用 Write 工具。
    """

    kind: Literal["Edit"] = "Edit"

    path: str = Field(
        ...,
        description="File path to edit (relative to workspace). The file must already exist.",
    )
    edits: list[EditOp] = Field(
        ...,
        description="Ordered list of find-and-replace operations to apply",
    )

    def execute(self) -> str:
        """顺序执行所有编辑操作，返回结果报告。"""
        root = get_workspace_root()

        # 1. 路径安全检查
        try:
            safe_path = safe_resolve_path(self.path, root)
        except ValueError as exc:
            return f"Error: {exc}"

        # 2. 读取原文件
        try:
            with open(safe_path, "r", encoding="utf-8") as fh:
                content = fh.read()
        except FileNotFoundError:
            return (
                f"Error: file not found '{self.path}'. "
                f"Use Write to create a new file first."
            )
        except IsADirectoryError:
            return f"Error: '{self.path}' is a directory, not a file"
        except PermissionError:
            return f"Error: permission denied reading '{self.path}'"
        except UnicodeDecodeError:
            return f"Error: '{self.path}' appears to be a binary file; cannot edit"
        except Exception as exc:
            return f"Error: {exc}"

        # 3. 依序应用编辑
        original_content = content
        for i, op in enumerate(self.edits):
            new_content, found = _fuzzy_replace(content, op.old_text, op.new_text)
            if not found:
                # 截取上下文供 LLM 纠错
                snippet = _snippet_around(original_content, op.old_text)
                return (
                    f"Error: edit #{i + 1} failed -- cannot find old_text in '{self.path}'.\n"
                    f"--- old_text ---\n{op.old_text}\n"
                    f"--- file excerpt around expected location ---\n{snippet}\n"
                    f"Hint: re-Read the file to get the exact current content."
                )
            content = new_content

        # 4. 回写文件
        try:
            with open(safe_path, "w", encoding="utf-8") as fh:
                fh.write(content)
        except PermissionError:
            return f"Error: permission denied writing '{self.path}'"
        except Exception as exc:
            return f"Error: {exc}"

        return f"Successfully applied {len(self.edits)} edit(s) to {self.path}."


# ============================================================
# 模糊查找替换
# ============================================================


def _fuzzy_replace(content: str, old_text: str, new_text: str) -> "tuple[str, bool]":
    """
    在 content 中查找 old_text 并替换为 new_text。
    返回 (新内容, 是否找到)。

    匹配策略：
    1. 精确子串匹配（首选）
    2. 规范化空白符后逐行匹配（容错缩进 / 空格差异）
    """
    # ---- 策略 1：精确匹配 ----
    if old_text in content:
        return content.replace(old_text, new_text, 1), True

    # ---- 策略 2：逐行规范化匹配 ----
    old_lines = old_text.splitlines()
    content_lines = content.splitlines()

    if len(old_lines) == 0:
        return content, False

    for i in range(len(content_lines) - len(old_lines) + 1):
        if all(
            _lines_match(content_lines[i + j], old_lines[j])
            for j in range(len(old_lines))
        ):
            new_lines = new_text.splitlines()
            result = content_lines[:i] + new_lines + content_lines[i + len(old_lines) :]
            return "\n".join(result), True

    return content, False


def _lines_match(a: str, b: str) -> bool:
    """比较两行，忽略前后空白及中间多空格差异。"""
    return " ".join(a.split()) == " ".join(b.split())


def _snippet_around(content: str, old_text: str, radius: int = 12) -> str:
    """
    在 content 中尝试定位 old_text 首行，返回周围若干行的摘录，
    供 LLM 纠错时参考。
    """
    first_line = old_text.splitlines()[0] if old_text.strip() else old_text
    content_lines = content.splitlines()

    # 尝试规范化匹配定位首行
    for i, line in enumerate(content_lines):
        if _lines_match(line, first_line):
            start = max(0, i - radius // 2)
            end = min(len(content_lines), i + radius // 2 + len(old_text.splitlines()))
            snippet_lines = content_lines[start:end]
            numbered = "\n".join(
                f"  {start + j + 1:>4} | {ln}" for j, ln in enumerate(snippet_lines)
            )
            return numbered

    # 回退：返回文件头部
    head = content_lines[:radius]
    return "\n".join(f"  {j + 1:>4} | {ln}" for j, ln in enumerate(head))
