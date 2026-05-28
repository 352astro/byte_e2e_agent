"""Glob 工具 — 文件路径匹配测试。"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent.tools.glob import Glob


def _mock_sandbox(workspace: Path):
    sb = MagicMock()
    sb.resolve_path.return_value = str(workspace)
    return sb


@pytest.mark.unit
@pytest.mark.asyncio
async def test_glob_matches_python_files():
    """匹配 *.py，结果排序。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.py").write_text("")
        (root / "sub").mkdir()
        (root / "sub" / "c.py").write_text("")
        (root / "not.txt").write_text("")

        sb = _mock_sandbox(root)
        output = await Glob(pattern="**/*.py").execute(sandbox=sb)
        assert "a.py" in output
        assert "sub/c.py" in output
        assert "not.txt" not in output


@pytest.mark.unit
@pytest.mark.asyncio
async def test_glob_no_match():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sb = _mock_sandbox(root)
        output = await Glob(pattern="**/*.py").execute(sandbox=sb)
        assert "No files matching" in output


@pytest.mark.unit
@pytest.mark.asyncio
async def test_glob_nonexistent_dir():
    """不存在的目录无匹配。"""
    sb = _mock_sandbox(Path("/nonexistent_xyz"))
    output = await Glob(pattern="**/*").execute(sandbox=sb)
    assert "No files matching" in output


@pytest.mark.unit
@pytest.mark.asyncio
async def test_glob_max_results_truncation():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for i in range(300):
            (root / f"{i}.txt").write_text("")
        sb = _mock_sandbox(root)
        output = await Glob(pattern="*.txt", max_results=50).execute(sandbox=sb)
        assert "50 of 300" in output
        assert "250 more" in output
