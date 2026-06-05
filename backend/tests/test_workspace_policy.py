"""Workspace root safety policy tests."""

from __future__ import annotations

from app.core.config import (
    PROJECT_ROOT,
    coerce_agent_workspace,
    playground_workspace,
    validate_agent_workspace,
)


def test_coerce_agent_workspace_redirects_project_root_to_playground():
    assert coerce_agent_workspace(PROJECT_ROOT) == playground_workspace()


def test_coerce_agent_workspace_redirects_project_child_to_playground():
    assert coerce_agent_workspace(PROJECT_ROOT / "backend") == playground_workspace()


def test_validate_agent_workspace_allows_playground():
    assert validate_agent_workspace(playground_workspace()) == playground_workspace()


def test_validate_agent_workspace_rejects_project_parent():
    try:
        validate_agent_workspace(PROJECT_ROOT.parent)
    except ValueError as exc:
        assert "Workspace cannot" in str(exc)
    else:
        raise AssertionError("PROJECT_ROOT parent should be rejected")


def test_validate_agent_workspace_allows_project_sibling(tmp_path):
    sibling = tmp_path / "workspace"
    sibling.mkdir()
    assert validate_agent_workspace(sibling) == str(sibling.resolve())
