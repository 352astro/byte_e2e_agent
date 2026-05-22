"""Edit 工具 — 委托 SandBox 执行查找替换。"""


from pydantic import BaseModel, Field

from agent.tools.base import BaseTool


class EditOp(BaseModel):
    old_text: str = Field(..., description="Exact text to find.")
    new_text: str = Field(..., description="Replacement text.")


class Edit(BaseTool):

    path: str = Field(..., description="File path to edit (relative to workspace).")
    edits: list[EditOp] = Field(..., description="Ordered find-and-replace ops.")

    async def execute(self, sandbox=None) -> str:
        ops = [{"old_text": e.old_text, "new_text": e.new_text} for e in self.edits]
        return await sandbox.edit_file(self.path, ops)


# ── Helpers (used by SandBox) ──────────────────────────────


def _fuzzy_replace(content: str, old_text: str, new_text: str) -> "tuple[str, bool]":
    if old_text in content:
        return content.replace(old_text, new_text, 1), True
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
    return " ".join(a.split()) == " ".join(b.split())


def _snippet_around(content: str, old_text: str, radius: int = 12) -> str:
    first_line = old_text.splitlines()[0] if old_text.strip() else old_text
    content_lines = content.splitlines()
    for i, line in enumerate(content_lines):
        if _lines_match(line, first_line):
            start = max(0, i - radius // 2)
            end = min(len(content_lines), i + radius // 2 + len(old_text.splitlines()))
            snippet_lines = content_lines[start:end]
            return "\n".join(
                f"  {start + j + 1:>4} | {ln}" for j, ln in enumerate(snippet_lines)
            )
    head = content_lines[:radius]
    return "\n".join(f"  {j + 1:>4} | {ln}" for j, ln in enumerate(head))
