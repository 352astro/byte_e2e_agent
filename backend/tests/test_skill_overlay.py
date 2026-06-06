"""Skill builtin/custom overlay behavior."""

from __future__ import annotations

import pytest

from agent.tools import skill as skill_module


def _write_skill(root, name: str, text: str) -> None:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def skill_roots(tmp_path, monkeypatch):
    builtin = tmp_path / "builtin"
    project = tmp_path / "project"
    monkeypatch.setattr(skill_module, "BUILTIN_SKILLS_ROOT", builtin)

    import app.core.config as config

    monkeypatch.setattr(config, "PROJECT_ROOT", project)
    monkeypatch.setattr(config, "AGENT_DATA_DIR", ".agent-data")
    return builtin, project / ".agent-data" / "skills"


def test_custom_skill_overrides_builtin(skill_roots):
    builtin, custom = skill_roots
    _write_skill(builtin, "debugging", "# Debugging\n\nBuiltin description.")
    _write_skill(custom, "debugging", "# Debugging\n\nCustom description.")

    skills = skill_module.scan_skills()

    assert len(skills) == 1
    assert skills[0].source == "custom"
    assert skills[0].has_builtin is True
    assert skills[0].overrides_builtin is True
    assert skills[0].description == "Custom description."


def test_restore_builtin_removes_custom_override(skill_roots):
    builtin, custom = skill_roots
    _write_skill(builtin, "debugging", "# Debugging\n\nBuiltin description.")
    _write_skill(custom, "debugging", "# Debugging\n\nCustom description.")

    skill_module.restore_builtin_skill("debugging")
    skill = skill_module.get_skill("debugging")

    assert skill is not None
    assert skill.source == "builtin"
    assert skill.description == "Builtin description."


def test_create_custom_skill_rejects_existing_effective_name(skill_roots):
    builtin, _custom = skill_roots
    _write_skill(builtin, "debugging", "# Debugging\n\nBuiltin description.")

    with pytest.raises(FileExistsError):
        skill_module.create_custom_skill("debugging", "# Debugging\n\nCustom.")

