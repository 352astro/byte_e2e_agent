"""Browser 工具测试。"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from agent.tools.browser import BrowserAct, BrowserInspect, BrowserOpen
from agent.tools.toolset import ToolSet


@pytest.mark.unit
class TestBrowserOpen:
    def test_missing_url_rejected(self):
        """url 必填。"""
        with pytest.raises(Exception):
            BrowserOpen()

    def test_valid_url_accepted(self):
        """url 合法则校验通过。"""
        tool = BrowserOpen(url="http://localhost:5173")
        assert tool.url == "http://localhost:5173"


@pytest.mark.unit
class TestBrowserAct:
    def test_missing_selector_rejected(self):
        with pytest.raises(Exception):
            BrowserAct(action="click")

    def test_invalid_action_rejected(self):
        with pytest.raises(Exception):
            BrowserAct(selector="button", action="invalid")  # type: ignore[arg-type]

    def test_valid_accepted(self):
        tool = BrowserAct(selector="#btn", action="click")
        assert tool.selector == "#btn"
        assert tool.action == "click"

    @pytest.mark.asyncio
    async def test_act_without_open_returns_error(self):
        """没先 BrowserOpen 就 BrowserAct 返回错误。"""
        tool = BrowserAct(selector="button", action="click")
        result = await tool.execute()
        assert "Error" in result or "not open" in result.lower()


@pytest.mark.unit
class TestBrowserInspect:
    def test_missing_prompt_rejected(self):
        with pytest.raises(Exception):
            BrowserInspect()

    def test_valid_accepted(self):
        tool = BrowserInspect(prompt="Check localhost:5173 for errors")
        assert "localhost" in tool.prompt

    @pytest.mark.asyncio
    async def test_without_scheduler_returns_error(self):
        tool = BrowserInspect(prompt="test")
        result = await tool.execute()
        assert "scheduler" in result.lower()

    @pytest.mark.asyncio
    async def test_subagent_toolset_is_restricted(self):
        """BrowserInspect 的 SubAgent 只有浏览器 + 文件工具。"""
        tool = BrowserInspect(prompt="test")
        # Simulate scheduler with _run_subagent
        mock_scheduler = MagicMock()

        async def _fake_run(sandbox, toolset, channel, prompt, max_steps):
            # Verify the toolset doesn't contain BrowserInspect itself
            names = [t.function_name() for t in toolset.tools]
            assert "BrowserInspect" not in names
            assert "BrowserOpen" in names
            assert "BrowserAct" in names
            assert "Read" in names
            assert "Write" not in names  # no editing
            assert "SubAgent" not in names  # no recursion
            return "SubAgent report"

        mock_scheduler._run_subagent = _fake_run
        result = await tool.execute(scheduler=mock_scheduler)
        assert result == "SubAgent report"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_browser_opens_real_page():
    """集成测试：Playwright 打开真实页面并返回 HTML + console。"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        pytest.skip("Playwright not installed")

    import http.server
    import threading

    # Start a tiny HTTP server
    html = "<html><head><title>TEST</title></head><body><button>Click</button></body></html>"

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        tool = BrowserOpen(url=f"http://127.0.0.1:{port}")
        result = await tool.execute()
        assert "TEST" in result
        assert "Click" in result
        assert "── HTML ──" in result
        assert "── Console ──" in result
    finally:
        server.shutdown()

    # Clean up Playwright
    from agent.tools.browser import _shutdown_browser

    await _shutdown_browser()
