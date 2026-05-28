"""Grep 工具 — 正则搜索内容测试。"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent.tools.grep import Grep


def _mock_sandbox(workspace: Path):
    sb = MagicMock()
    sb.resolve_path.return_value = str(workspace)
    return sb


@pytest.mark.unit
@pytest.mark.asyncio
async def test_grep_finds_matching_lines():
    """匹配行返回 file:lineno: content。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.py").write_text("import os\nprint(1)\n")
        (root / "b.py").write_text("x = 1\ny = 2\n")

        sb = _mock_sandbox(root)
        output = await Grep(regex=r"import").execute(sandbox=sb)
        assert "a.py:1: import os" in output


@pytest.mark.unit
@pytest.mark.asyncio
async def test_grep_no_match_reports_scanned():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.py").write_text("hello\nworld\n")
        sb = _mock_sandbox(root)
        output = await Grep(regex=r"xyzzy_nonexistent").execute(sandbox=sb)
        assert "No matches" in output
        assert "scanned" in output


@pytest.mark.unit
@pytest.mark.asyncio
async def test_grep_skips_binary():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.py").write_text("hello\n")
        (root / "b.bin").write_bytes(b"\x80\xff\xfe\x00")
        sb = _mock_sandbox(root)
        output = await Grep(regex=r"hello", include_pattern="**/*").execute(sandbox=sb)
        assert "a.py:1: hello" in output
        assert "scanned 1 file" in output.lower() or "in 1 file" in output


@pytest.mark.unit
@pytest.mark.asyncio
async def test_grep_invalid_regex():
    sb = _mock_sandbox(Path("/tmp"))
    output = await Grep(regex=r"[").execute(sandbox=sb)
    assert "Error" in output or "invalid" in output.lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_grep_max_results_stops_early():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        lines = "\n".join(f"line{i}" for i in range(100))
        (root / "big.py").write_text(lines)
        sb = _mock_sandbox(root)
        output = await Grep(regex=r"line", max_results=5).execute(sandbox=sb)
        assert "5 match" in output
