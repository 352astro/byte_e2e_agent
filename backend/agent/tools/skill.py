"""Skill 加载器。

每个 Skill 是一个放在 ``agent/skills/<name>/Skill.md`` 的特化能力模块。
Skill 上下文消息注入摘要；需要执行该能力时，模型再通过 LoadSkill 读取完整内容。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import Field

from agent.tools.base import BaseTool

SKILLS_ROOT = Path(__file__).resolve().parent.parent / "skills"
SKILL_FILE = "Skill.md"


@dataclass(frozen=True)
class SkillInfo:
    """已发现的 Skill，以及注入给模型的摘要。"""

    name: str
    description: str
    path: Path

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")


def scan_skills() -> list[SkillInfo]:
    """扫描所有 ``skills/<name>/Skill.md`` 并返回摘要信息。"""
    if not SKILLS_ROOT.is_dir():
        return []

    skills: list[SkillInfo] = []
    for entry in sorted(SKILLS_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        path = entry / SKILL_FILE
        if not path.is_file():
            continue
        skills.append(
            SkillInfo(
                name=entry.name,
                description=_extract_description(path),
                path=path,
            )
        )
    return skills


def get_skill(name: str) -> SkillInfo | None:
    """按目录名获取 Skill。"""
    return next((skill for skill in scan_skills() if skill.name == name), None)


def get_skills_summary() -> str:
    """生成注入 Skill 上下文消息的摘要列表。"""
    skills = scan_skills()
    if not skills:
        return "(No skills available.)"
    lines = []
    for s in skills:
        lines.append(f"- {s.name}: {s.description}")
    return "\n".join(lines)


def skill_context_message() -> dict:
    """返回本轮可用 Skill 列表的系统消息。"""
    content = "\n".join(
        [
            "## Available Skills",
            "Skills are specialized capability modules.",
            "This list is reloaded before each model step.",
            "When a skill matches the task, call LoadSkill with its name, "
            "read the full Skill content, then continue with normal tools.",
            get_skills_summary(),
        ]
    )
    return {"role": "system", "content": content}


def _extract_description(md_file: Path) -> str:
    """提取一级标题后的第一个普通段落作为摘要。"""
    try:
        text = md_file.read_text(encoding="utf-8")
    except Exception:
        return "(cannot read)"

    in_body = False
    paragraph: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not in_body:
            if line.startswith("# "):
                in_body = True
            continue

        if not line:
            if paragraph:
                break
            continue
        if line.startswith("#"):
            if paragraph:
                break
            continue
        paragraph.append(line)

    return " ".join(paragraph) if paragraph else "(no description)"


class LoadSkill(BaseTool):
    """加载指定 Skill 的完整内容。"""

    name: str = Field(..., description="Skill 目录名。")

    async def execute(self, *, sandbox=None, channel=None, interrupt_event=None, scheduler=None, toolset=None, result_id="") -> str:
        skill = get_skill(self.name)
        if skill is None:
            available = [s.name for s in scan_skills()]
            return (
                f"Skill '{self.name}' not found. "
                f"Available skills: {', '.join(available) if available else 'none'}"
            )
        return skill.read()
