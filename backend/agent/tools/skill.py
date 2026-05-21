"""
Skill 系统 — 可插拔的知识模块。

每个 Skill 以 Markdown 文件形式存放在 ``agent/skills/<name>/Skill.md``。
本模块负责扫描技能目录、生成摘要供 system prompt 注入，
并提供 LoadSkill 工具供 LLM 按需获取完整内容。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field

from agent.tools.base import BaseTool

# ── Skill 目录 ────────────────────────────────────────────

_SKILLS_ROOT = Path(__file__).resolve().parent.parent / "skills"


# ── 数据结构 ──────────────────────────────────────────────


class SkillInfo:
    """技能摘要信息（注入 system prompt）。"""

    def __init__(self, name: str, description: str, path: Path) -> None:
        self.name = name
        self.description = description
        self._path = path

    def full_content(self) -> str:
        """读取 Skill.md 完整内容。"""
        return self._path.read_text(encoding="utf-8")


# ── 扫描 ──────────────────────────────────────────────────


def scan_skills() -> list[SkillInfo]:
    """扫描 skills 目录，返回所有可用技能的摘要列表。"""
    result: list[SkillInfo] = []
    if not _SKILLS_ROOT.is_dir():
        return result

    for entry in sorted(_SKILLS_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        md_file = entry / "Skill.md"
        if not md_file.is_file():
            continue

        name = entry.name
        description = _extract_description(md_file)
        result.append(SkillInfo(name, description, md_file))

    return result


def get_skill(name: str) -> SkillInfo | None:
    """按名称获取技能；找不到返回 None。"""
    md_file = _SKILLS_ROOT / name / "Skill.md"
    if not md_file.is_file():
        return None
    return SkillInfo(name, _extract_description(md_file), md_file)


def get_skills_summary() -> str:
    """生成可注入 system prompt 的技能摘要文本。"""
    skills = scan_skills()
    if not skills:
        return "(No skills available.)"
    lines = ["Available skills (use LoadSkill to get full details):"]
    for s in skills:
        lines.append(f"  - **{s.name}**: {s.description}")
    return "\n".join(lines)


# ── 内部 ──────────────────────────────────────────────────


def _extract_description(md_file: Path) -> str:
    """从 Markdown 文件提取描述（跳过标题行后的第一个非空段落）。"""
    try:
        text = md_file.read_text(encoding="utf-8")
    except Exception:
        return "(cannot read)"

    lines = text.splitlines()
    past_heading = False
    desc_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not past_heading:
            if stripped.startswith("# ") and not stripped.startswith("## "):
                past_heading = True
            continue
        if stripped == "" and desc_lines:
            break  # first paragraph ended
        if stripped:
            desc_lines.append(stripped)

    return " ".join(desc_lines) if desc_lines else "(no description)"


# ── LoadSkill 工具 ────────────────────────────────────────


class LoadSkill(BaseTool):
    """
    加载指定 Skill 的完整 Markdown 内容。

    当 LLM 需要某个技能的详细指引时调用此工具。
    技能的简要信息已在 system prompt 中列出。
    """

    kind: Literal["LoadSkill"] = "LoadSkill"

    name: str = Field(
        ...,
        description="Name of the skill to load (directory name under skills/).",
    )

    def execute(self) -> str:
        """读取并返回 Skill.md 的完整内容。"""
        skill = get_skill(self.name)
        if skill is None:
            available = [s.name for s in scan_skills()]
            return (
                f"Skill '{self.name}' not found. "
                f"Available skills: {', '.join(available) if available else 'none'}"
            )
        return skill.full_content()
