"""Skill 加载器。

每个 Skill 是一个放在 ``agent/skills/<name>/SKILL.md`` 的特化能力模块。
Skill 上下文消息注入摘要；需要执行该能力时，模型再通过 LoadSkill 读取完整内容。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

BUILTIN_SKILLS_ROOT = Path(__file__).resolve().parent.parent / "skills"
SKILL_FILE = "SKILL.md"
_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class SkillInfo:
    """已发现的 Skill，以及注入给模型的摘要。"""

    name: str
    description: str
    path: Path
    source: Literal["builtin", "custom"] = "builtin"
    has_builtin: bool = False
    overrides_builtin: bool = False

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")


def custom_skills_root() -> Path:
    from app.core.config import AGENT_DATA_DIR, PROJECT_ROOT

    return PROJECT_ROOT / AGENT_DATA_DIR / "skills"


def scan_skills() -> list[SkillInfo]:
    """扫描 builtin/custom skills 并返回 custom 覆盖后的有效列表。"""
    builtin = _scan_skill_root(BUILTIN_SKILLS_ROOT, source="builtin")
    custom = _scan_skill_root(custom_skills_root(), source="custom")

    merged: dict[str, SkillInfo] = {}
    for name, skill in builtin.items():
        merged[name] = SkillInfo(
            name=skill.name,
            description=skill.description,
            path=skill.path,
            source="builtin",
            has_builtin=True,
            overrides_builtin=False,
        )
    for name, skill in custom.items():
        has_builtin = name in builtin
        merged[name] = SkillInfo(
            name=skill.name,
            description=skill.description,
            path=skill.path,
            source="custom",
            has_builtin=has_builtin,
            overrides_builtin=has_builtin,
        )
    return [merged[name] for name in sorted(merged)]


def get_skill(name: str) -> SkillInfo | None:
    """按目录名获取 Skill。"""
    return next((skill for skill in scan_skills() if skill.name == name), None)


def read_skill_detail(name: str) -> dict | None:
    skill = get_skill(name)
    if skill is None:
        return None
    return {
        "name": skill.name,
        "description": skill.description,
        "source": skill.source,
        "has_builtin": skill.has_builtin,
        "overrides_builtin": skill.overrides_builtin,
        "content": skill.read(),
    }


def create_custom_skill(name: str, content: str) -> SkillInfo:
    """Create a brand-new custom skill. Existing effective names conflict."""
    _validate_skill_name(name)
    if get_skill(name) is not None:
        raise FileExistsError(f"Skill already exists: {name}")
    return _write_custom_skill(name, content)


def upsert_custom_skill(name: str, content: str) -> SkillInfo:
    """Create or update a custom skill, including builtin overrides."""
    _validate_skill_name(name)
    return _write_custom_skill(name, content)


def delete_custom_skill(name: str) -> None:
    _validate_skill_name(name)
    path = _custom_skill_dir(name)
    if not path.is_dir():
        raise FileNotFoundError(f"Custom skill not found: {name}")
    shutil.rmtree(path)


def restore_builtin_skill(name: str) -> None:
    _validate_skill_name(name)
    if not _builtin_skill_path(name).is_file():
        raise FileNotFoundError(f"Builtin skill not found: {name}")
    path = _custom_skill_dir(name)
    if path.is_dir():
        shutil.rmtree(path)


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


def _scan_skill_root(
    root: Path,
    *,
    source: Literal["builtin", "custom"],
) -> dict[str, SkillInfo]:
    if not root.is_dir():
        return {}
    skills: dict[str, SkillInfo] = {}
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not _SKILL_NAME_RE.fullmatch(entry.name):
            continue
        path = entry / SKILL_FILE
        if not path.is_file():
            continue
        skills[entry.name] = SkillInfo(
            name=entry.name,
            description=_extract_description(path),
            path=path,
            source=source,
        )
    return skills


def _validate_skill_name(name: str) -> None:
    if not _SKILL_NAME_RE.fullmatch(name):
        raise ValueError(
            "Skill name must match ^[a-z0-9][a-z0-9-]*$"
        )


def _custom_skill_dir(name: str) -> Path:
    _validate_skill_name(name)
    return custom_skills_root() / name


def _custom_skill_path(name: str) -> Path:
    return _custom_skill_dir(name) / SKILL_FILE


def _builtin_skill_path(name: str) -> Path:
    _validate_skill_name(name)
    return BUILTIN_SKILLS_ROOT / name / SKILL_FILE


def _write_custom_skill(name: str, content: str) -> SkillInfo:
    if not content.strip():
        raise ValueError("Skill content is required")
    path = _custom_skill_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    skill = get_skill(name)
    if skill is None:
        raise RuntimeError(f"Failed to load saved skill: {name}")
    return skill


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


class LoadSkillInput(BaseModel):
    """LoadSkill 工具输入参数。"""

    name: str = Field(..., description="Skill 目录名。")


async def load_skill_handler(name: str, *, ws=None) -> str:
    """加载指定 Skill 的完整内容。"""
    skill = get_skill(name)
    if skill is None:
        available = [s.name for s in scan_skills()]
        return (
            f"Skill '{name}' not found. "
            f"Available skills: {', '.join(available) if available else 'none'}"
        )
    return skill.read()


load_skill_tool = StructuredTool.from_function(
    coroutine=load_skill_handler,
    name="LoadSkill",
    description="Load the full content of a Skill by name.",
    args_schema=LoadSkillInput,
)
