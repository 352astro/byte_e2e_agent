"""Tool execution and interrupt tests — every tool individually.

Tests cover:
- Basic execution (mock-backed, no real side effects)
- Interrupt behavior: before-start + mid-execution
- Tools that do NOT support interrupt_event → @pytest.mark.skip with reason

── 设计原则 ──
- Mock-First: 所有外部依赖（文件系统、网络、子进程）都用 mock
- 每个工具至少有一个基本执行测试
- 支持 interrupt 的工具测试打断态（开始前/进行中）
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.tools import tool_registry
from agent.tools.toolset import ToolSet

# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _get_handler(tool_name: str):
    """Get the coroutine handler for a tool by name."""
    tool = tool_registry.get(tool_name)
    assert tool is not None, f"Tool '{tool_name}' not registered"
    return tool.coroutine


def _make_ws(read_file_ret=None, write_file_ret=None, edit_file_ret=None, resolve_path_ret=None):
    """Create a mock Workspace."""
    ws = MagicMock()
    ws.read_file = AsyncMock(return_value=read_file_ret or "(empty)")
    ws.write_file = AsyncMock(return_value=write_file_ret or "Successfully wrote file.")
    ws.edit_file = AsyncMock(return_value=edit_file_ret or "Successfully applied edit(s).")
    ws.resolve_path.return_value = resolve_path_ret or "/mock/workspace"
    ws.root = Path("/mock/workspace")
    return ws


# ═══════════════════════════════════════════════════════════
# Shell
# ═══════════════════════════════════════════════════════════


class TestShellExecution:
    """Shell tool — supports interrupt_event. Real PTY execution, no mocks."""

    @pytest.mark.asyncio
    async def test_basic_execution(self, tmp_path):
        """Shell executes a command and returns output."""
        from agent.core.workspace import Workspace

        handler = _get_handler("Shell")
        ws = Workspace(tmp_path)

        result = await handler(command="echo hello", ws=ws)
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_nonzero_exit_code(self, tmp_path):
        """Shell returns exit code annotation for nonzero."""
        from agent.core.workspace import Workspace

        handler = _get_handler("Shell")
        ws = Workspace(tmp_path)

        result = await handler(command="exit 7", ws=ws)
        assert "exit code: 7" in result

    @pytest.mark.asyncio
    async def test_timeout(self, tmp_path):
        """Shell returns timeout annotation when command exceeds timeout_ms.

        sleep 120 >> timeout_ms=1000, so the command is guaranteed to hit
        the timeout rather than complete naturally.
        """
        from agent.core.workspace import Workspace

        handler = _get_handler("Shell")
        ws = Workspace(tmp_path)

        result = await handler(command="sleep 120", timeout_ms=1000, ws=ws)
        assert "timed out" in result.lower()
        assert "interrupted" not in result.lower()

    @pytest.mark.asyncio
    async def test_interrupt_before_start(self, tmp_path):
        """Shell with pre-set interrupt_event returns interrupted.

        sleep 120 >> timeout_ms=5000. interrupt_event.set() before handler
        call → handler polls, sees the event, sends SIGINT to bash → bash
        forwards to sleep → sleep exits → result returns in <2s with
        'interrupted'. Timing assertion proves it was interrupt (fast),
        not timeout (would take 5s).
        """
        import time

        from agent.core.workspace import Workspace

        handler = _get_handler("Shell")
        ws = Workspace(tmp_path)
        interrupt_event = asyncio.Event()
        interrupt_event.set()

        t0 = time.perf_counter()
        result = await handler(
            command="sleep 120",
            timeout_ms=5000,
            ws=ws,
            interrupt_event=interrupt_event,
        )
        elapsed = time.perf_counter() - t0

        assert "interrupted" in result.lower(), f"got: {result}"
        assert "timed out" not in result.lower()
        assert elapsed < 3.0, f"Interrupt took {elapsed:.1f}s — should be <3s"

    @pytest.mark.asyncio
    async def test_interrupt_mid_execution(self, tmp_path):
        """Shell interrupted during execution.

        Fires interrupt 200ms after start. Timing assertion proves it
        was the interrupt (fast return) not timeout (5s).
        """
        import time

        from agent.core.workspace import Workspace

        handler = _get_handler("Shell")
        ws = Workspace(tmp_path)
        interrupt_event = asyncio.Event()

        async def trigger():
            await asyncio.sleep(0.2)
            interrupt_event.set()

        task = asyncio.create_task(trigger())
        t0 = time.perf_counter()
        result = await handler(
            command="sleep 120",
            timeout_ms=5000,
            ws=ws,
            interrupt_event=interrupt_event,
        )
        elapsed = time.perf_counter() - t0
        await task

        assert "interrupted" in result.lower(), f"got: {result}"
        assert "timed out" not in result.lower()
        assert elapsed < 3.0, f"Interrupt took {elapsed:.1f}s — should be <3s"


# ═══════════════════════════════════════════════════════════
# Read
# ═══════════════════════════════════════════════════════════


class TestReadExecution:
    """Read tool — does NOT support interrupt_event."""

    @pytest.mark.asyncio
    async def test_basic_execution(self):
        """Read returns file content."""
        handler = _get_handler("Read")
        ws = _make_ws(read_file_ret="line1\nline2\nline3")

        result = await handler(path="test.py", ws=ws)
        assert "line1" in result
        assert "line2" in result

    @pytest.mark.asyncio
    async def test_with_line_range(self):
        """Read with start_line and end_line returns sliced content."""
        handler = _get_handler("Read")
        ws = _make_ws(read_file_ret="a\nb\nc\nd\ne")

        result = await handler(path="test.py", start_line=2, end_line=4, ws=ws)
        assert "b" in result
        assert "c" in result
        assert "d" in result
        assert "[lines 2-4" in result

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        """Read returns error for missing file."""
        handler = _get_handler("Read")
        ws = _make_ws(read_file_ret="Error: file not found")

        result = await handler(path="nope.txt", ws=ws)
        assert "Error" in result or "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_interrupt_not_supported(self):
        """Read does NOT accept interrupt_event — skipped."""
        pytest.skip("Read tool does not support interrupt_event")


# ═══════════════════════════════════════════════════════════
# Write
# ═══════════════════════════════════════════════════════════


class TestWriteExecution:
    """Write tool — does NOT support interrupt_event."""

    @pytest.mark.asyncio
    async def test_basic_execution(self):
        """Write creates a file."""
        handler = _get_handler("Write")
        ws = _make_ws()

        result = await handler(path="new.py", content="print(1)", ws=ws)
        assert "Successfully" in result

    @pytest.mark.asyncio
    async def test_write_error(self):
        """Write returns error on failure."""
        handler = _get_handler("Write")
        ws = _make_ws(write_file_ret="Error: permission denied")

        result = await handler(path="/root/x.py", content="bad", ws=ws)
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_interrupt_not_supported(self):
        pytest.skip("Write tool does not support interrupt_event")


# ═══════════════════════════════════════════════════════════
# Edit
# ═══════════════════════════════════════════════════════════


class TestEditExecution:
    """Edit tool — does NOT support interrupt_event."""

    @pytest.mark.asyncio
    async def test_basic_execution(self):
        """Edit applies find-and-replace."""
        handler = _get_handler("Edit")
        ws = _make_ws()

        result = await handler(
            path="test.py",
            edits=[{"old_text": "a", "new_text": "b"}],
            ws=ws,
        )
        assert "Successfully" in result

    @pytest.mark.asyncio
    async def test_edit_error(self):
        """Edit returns error on failure."""
        handler = _get_handler("Edit")
        ws = _make_ws(edit_file_ret="Error: cannot find old_text")

        result = await handler(
            path="test.py",
            edits=[{"old_text": "missing", "new_text": "x"}],
            ws=ws,
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_interrupt_not_supported(self):
        pytest.skip("Edit tool does not support interrupt_event")


# ═══════════════════════════════════════════════════════════
# Glob
# ═══════════════════════════════════════════════════════════


class TestGlobExecution:
    """Glob tool — does NOT support interrupt_event."""

    @pytest.mark.asyncio
    async def test_basic_execution(self, tmp_path):
        """Glob finds files matching a pattern."""
        handler = _get_handler("Glob")
        ws = _make_ws(resolve_path_ret=str(tmp_path))

        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / "c.txt").write_text("")

        result = await handler(pattern="*.py", ws=ws)
        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" not in result

    @pytest.mark.asyncio
    async def test_no_matches(self, tmp_path):
        """Glob returns 'No files' when nothing matches."""
        handler = _get_handler("Glob")
        ws = _make_ws(resolve_path_ret=str(tmp_path))

        result = await handler(pattern="*.js", ws=ws)
        assert "No files matching" in result

    @pytest.mark.asyncio
    async def test_interrupt_not_supported(self):
        pytest.skip("Glob tool does not support interrupt_event")


# ═══════════════════════════════════════════════════════════
# Grep
# ═══════════════════════════════════════════════════════════


class TestGrepExecution:
    """Grep tool — does NOT support interrupt_event."""

    @pytest.mark.asyncio
    async def test_basic_execution(self, tmp_path):
        """Grep finds a regex pattern in files."""
        handler = _get_handler("Grep")
        ws = _make_ws(resolve_path_ret=str(tmp_path))

        (tmp_path / "a.py").write_text("def foo():\n    pass\n")
        (tmp_path / "b.py").write_text("def bar():\n    pass\n")

        result = await handler(regex=r"def \w+", ws=ws)
        assert "foo" in result
        assert "bar" in result

    @pytest.mark.asyncio
    async def test_no_matches(self, tmp_path):
        """Grep returns 'No matches' when nothing found."""
        handler = _get_handler("Grep")
        ws = _make_ws(resolve_path_ret=str(tmp_path))

        (tmp_path / "a.py").write_text("hello")

        result = await handler(regex="zzzzNOTFOUNDzzzz", ws=ws)
        assert "No matches" in result

    @pytest.mark.asyncio
    async def test_invalid_regex(self, tmp_path):
        """Grep returns error for invalid regex."""
        handler = _get_handler("Grep")
        ws = _make_ws(resolve_path_ret=str(tmp_path))

        result = await handler(regex="[open", ws=ws)
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_interrupt_not_supported(self):
        pytest.skip("Grep tool does not support interrupt_event")


# ═══════════════════════════════════════════════════════════
# PyRepl
# ═══════════════════════════════════════════════════════════


class TestPyReplExecution:
    """PyRepl tool — supports interrupt_event."""

    @pytest.mark.asyncio
    async def test_basic_execution(self):
        """PyRepl runs Python code in subprocess."""
        handler = _get_handler("PyRepl")

        with patch("agent.tools.pyrepl.asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"42\n", b""))
            mock_proc.wait = AsyncMock()
            mock_exec.return_value = mock_proc

            result = await handler(code="print(6*7)")
            assert "42" in result

    @pytest.mark.asyncio
    async def test_interrupt_before_start(self):
        """PyRepl with pre-set interrupt_event returns interrupted."""
        handler = _get_handler("PyRepl")
        interrupt_event = asyncio.Event()
        interrupt_event.set()

        with patch("agent.tools.pyrepl.asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.pid = 99999
            mock_exec.return_value = mock_proc

            result = await handler(code="print(1)", interrupt_event=interrupt_event)
            assert "interrupted" in result.lower()

    @pytest.mark.asyncio
    async def test_interrupt_mid_execution(self):
        """PyRepl interrupted during subprocess execution."""
        handler = _get_handler("PyRepl")
        interrupt_event = asyncio.Event()

        with patch("agent.tools.pyrepl.asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.pid = 99999  # safe non-existent PID

            async def slow_communicate():
                await asyncio.sleep(1)
                return (b"partial", b"")

            mock_proc.communicate = slow_communicate
            mock_proc.wait = AsyncMock()
            mock_exec.return_value = mock_proc

            async def trigger():
                await asyncio.sleep(0.05)
                interrupt_event.set()

            task = asyncio.create_task(trigger())
            result = await handler(code="while True: pass", interrupt_event=interrupt_event)
            await task
            # Either interrupted or timed out
            assert "interrupted" in result.lower() or "timed out" in result.lower()

    @pytest.mark.asyncio
    async def test_timeout(self):
        """PyRepl times out on slow code."""
        handler = _get_handler("PyRepl")

        with patch("agent.tools.pyrepl.asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.pid = 99999  # safe non-existent PID

            async def hang():
                await asyncio.sleep(10)
                return (b"", b"")

            mock_proc.communicate = hang
            mock_proc.wait = AsyncMock()
            mock_exec.return_value = mock_proc

            result = await handler(code="while True: pass", timeout_ms=100)
            assert "timed out" in result.lower()


# ═══════════════════════════════════════════════════════════
# WebSearch
# ═══════════════════════════════════════════════════════════


class TestWebSearchExecution:
    """WebSearch tool — supports interrupt_event."""

    @pytest.mark.asyncio
    async def test_basic_execution(self):
        """WebSearch calls SerpApi and returns formatted results."""
        handler = _get_handler("WebSearch")

        with patch("agent.tools.search.serpapi.Client") as MockClient:
            mock_client = MockClient.return_value
            mock_client.search.return_value = {
                "organic_results": [
                    {"title": "Result 1", "snippet": "Snippet 1"},
                    {"title": "Result 2", "snippet": "Snippet 2"},
                ]
            }

            result = await handler(query="test query")
            assert "Result 1" in result
            assert "Snippet 1" in result

    @pytest.mark.asyncio
    async def test_interrupt_before_start(self):
        """WebSearch with pre-set interrupt_event returns interrupted."""
        handler = _get_handler("WebSearch")
        interrupt_event = asyncio.Event()
        interrupt_event.set()

        result = await handler(query="test", interrupt_event=interrupt_event)
        assert "interrupted" in result.lower()

    @pytest.mark.asyncio
    async def test_interrupt_after_search(self):
        """WebSearch interrupted after search completes but before format."""
        handler = _get_handler("WebSearch")
        interrupt_event = asyncio.Event()

        with patch("agent.tools.search.serpapi.Client") as MockClient:
            mock_client = MockClient.return_value
            mock_client.search.return_value = {"organic_results": []}

            # Set interrupt after the search (simulates interrupt during format)
            original_search = mock_client.search

            def search_and_interrupt(*args, **kwargs):
                interrupt_event.set()
                return original_search(*args, **kwargs)

            mock_client.search = search_and_interrupt

            result = await handler(query="test", interrupt_event=interrupt_event)
            assert "interrupted" in result.lower()

    @pytest.mark.asyncio
    async def test_no_api_key(self):
        """WebSearch returns error when SERPAPI_KEY is missing."""
        handler = _get_handler("WebSearch")

        with patch.dict(os.environ, {}, clear=True):
            with patch("agent.tools.search.serpapi.Client") as MockClient:
                mock_client = MockClient.return_value
                mock_client.search.side_effect = RuntimeError("SERPAPI_KEY is not configured")

                result = await handler(query="test")
                assert "Error" in result


# ═══════════════════════════════════════════════════════════
# WebFetch
# ═══════════════════════════════════════════════════════════


class _FakeResponse:
    """A fake httpx response supporting async iteration over aiter_bytes."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self._closed = False

    def aiter_bytes(self, chunk_size: int = 8192):
        return self

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self._closed = True


class _FakeStreamCtx:
    """Fake async context manager for client.stream()."""

    def __init__(self, resp: _FakeResponse) -> None:
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *args) -> None:
        pass


class _FakeClient:
    """Fake httpx.AsyncClient supporting async context manager."""

    def __init__(self, stream_ctx=None) -> None:
        self.stream_ctx = stream_ctx

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        pass

    def stream(self, method: str, url: str, **kwargs):
        return self.stream_ctx


class TestWebFetchExecution:
    """WebFetch tool — supports interrupt_event."""

    @pytest.mark.asyncio
    async def test_basic_execution(self):
        """WebFetch fetches a URL and returns content."""
        handler = _get_handler("WebFetch")

        fake_resp = _FakeResponse([b"hello ", b"world"])
        fake_client = _FakeClient(stream_ctx=_FakeStreamCtx(fake_resp))

        with patch("agent.tools.search.httpx.AsyncClient", return_value=fake_client):
            result = await handler(url="http://example.com")
            assert "hello" in result
            assert "world" in result

    @pytest.mark.asyncio
    async def test_interrupt_before_start(self):
        """WebFetch with pre-set interrupt_event returns interrupted."""
        handler = _get_handler("WebFetch")
        interrupt_event = asyncio.Event()
        interrupt_event.set()

        result = await handler(url="http://example.com", interrupt_event=interrupt_event)
        assert "interrupted" in result.lower()

    @pytest.mark.asyncio
    async def test_interrupt_mid_stream(self):
        """WebFetch interrupted during streaming."""
        handler = _get_handler("WebFetch")
        interrupt_event = asyncio.Event()

        async def interruptable_chunks():
            yield b"chunk1"
            interrupt_event.set()
            await asyncio.sleep(0.1)
            yield b"chunk2"

        class InterruptableAiter:
            def __aiter__(self):
                return interruptable_chunks()

        fake_resp = _FakeResponse([b"dummy"])
        fake_resp.aiter_bytes = lambda chunk_size=8192: InterruptableAiter()
        fake_client = _FakeClient(stream_ctx=_FakeStreamCtx(fake_resp))

        with patch("agent.tools.search.httpx.AsyncClient", return_value=fake_client):
            result = await handler(url="http://example.com", interrupt_event=interrupt_event)
            assert "interrupted" in result.lower()


# ═══════════════════════════════════════════════════════════
# LoadSkill
# ═══════════════════════════════════════════════════════════


class TestLoadSkillExecution:
    """LoadSkill tool — does NOT support interrupt_event."""

    @pytest.mark.asyncio
    async def test_basic_execution(self):
        """LoadSkill returns skill content if found."""
        handler = _get_handler("LoadSkill")

        with patch("agent.tools.skill.scan_skills") as mock_scan:
            mock_skill = MagicMock()
            mock_skill.name = "test-skill"
            mock_skill.read.return_value = "# Test Skill\n\nContent here."
            mock_scan.return_value = [mock_skill]

            result = await handler(name="test-skill")
            assert "Test Skill" in result

    @pytest.mark.asyncio
    async def test_skill_not_found(self):
        """LoadSkill returns error for unknown skill."""
        handler = _get_handler("LoadSkill")

        with patch("agent.tools.skill.scan_skills") as mock_scan:
            mock_scan.return_value = []
            result = await handler(name="nonexistent")
            assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_interrupt_not_supported(self):
        pytest.skip("LoadSkill tool does not support interrupt_event")


# ═══════════════════════════════════════════════════════════
# SubAgent
# ═══════════════════════════════════════════════════════════


class TestSubAgentExecution:
    """SubAgent tool — dispatched externally, does NOT support interrupt_event."""

    @pytest.mark.asyncio
    async def test_direct_call_returns_error(self):
        """SubAgent called directly returns dispatch error."""
        handler = _get_handler("SubAgent")
        result = await handler(prompt="do something")
        assert "must be dispatched" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_interrupt_not_supported(self):
        pytest.skip(
            "SubAgent tool is dispatched externally, does not support "
            "interrupt_event at handler level"
        )


# ═══════════════════════════════════════════════════════════
# BrowserOpen
# ═══════════════════════════════════════════════════════════


class TestBrowserOpenExecution:
    """BrowserOpen tool — accepts interrupt_event parameter but relies on Playwright."""

    @pytest.mark.asyncio
    async def test_basic_execution(self):
        """BrowserOpen navigates to a URL."""
        handler = _get_handler("BrowserOpen")

        with patch("agent.tools.browser._ensure_browser") as mock_browser:
            mock_page = AsyncMock()
            mock_page.content = AsyncMock(return_value="<html>test</html>")
            mock_page.url = "http://example.com"
            mock_page.title = AsyncMock(return_value="Example")
            mock_browser.return_value = mock_page

            result = await handler(url="http://example.com")
            assert "Example" in result or "test" in result

    @pytest.mark.asyncio
    async def test_session_id_uses_per_session_browser(self):
        """BrowserOpen routes ordinary calls through the per-session manager."""
        handler = _get_handler("BrowserOpen")

        with patch("agent.tools.browser._ensure_browser") as mock_browser:
            mock_page = AsyncMock()
            mock_page.on = MagicMock()
            mock_page.content = AsyncMock(return_value="<html>session</html>")
            mock_page.url = "http://example.com"
            mock_page.title = AsyncMock(return_value="Session Browser")
            mock_browser.return_value = mock_page

            result = await handler(url="http://example.com", session_id="sid-a")

        mock_browser.assert_called_once_with(session_id="sid-a")
        assert "Session Browser" in result or "session" in result

    @pytest.mark.asyncio
    async def test_interrupt_not_supported(self):
        pytest.skip(
            "BrowserOpen accepts interrupt_event parameter but "
            "does not meaningfully use it during Playwright navigation"
        )


# ═══════════════════════════════════════════════════════════
# BrowserAct
# ═══════════════════════════════════════════════════════════


class TestBrowserActExecution:
    """BrowserAct tool — supports interrupt_event."""

    @pytest.mark.asyncio
    async def test_basic_execution(self):
        """BrowserAct performs click action."""
        handler = _get_handler("BrowserAct")

        with patch("agent.tools.browser._page") as mock_page:
            mock_page = AsyncMock()
            mock_page.click = AsyncMock()
            mock_page.content = AsyncMock(return_value="<html>clicked</html>")
            mock_page.url = "http://example.com"
            mock_page.title = AsyncMock(return_value="After Click")

            # Inject the mock page
            import agent.tools.browser as browser_mod

            old_page = browser_mod._page
            browser_mod._page = mock_page
            try:
                result = await handler(selector="#btn", action="click")
                assert "After Click" in result or "clicked" in result
            finally:
                browser_mod._page = old_page

    @pytest.mark.asyncio
    async def test_interrupt_before_start(self):
        """BrowserAct with pre-set interrupt_event returns interrupted."""
        handler = _get_handler("BrowserAct")
        interrupt_event = asyncio.Event()
        interrupt_event.set()

        result = await handler(selector="#btn", action="click", interrupt_event=interrupt_event)
        assert "interrupted" in result.lower()

    @pytest.mark.asyncio
    async def test_no_browser_open(self):
        """BrowserAct returns error when no browser page is open."""
        handler = _get_handler("BrowserAct")

        import agent.tools.browser as browser_mod

        old_page = browser_mod._page
        browser_mod._page = None
        try:
            result = await handler(selector="#btn", action="click")
            assert "Error" in result or "Browser not open" in result
        finally:
            browser_mod._page = old_page


# ═══════════════════════════════════════════════════════════
# BrowserInspect
# ═══════════════════════════════════════════════════════════


class TestBrowserInspectExecution:
    """BrowserInspect tool — dispatched externally, does NOT support interrupt_event."""

    @pytest.mark.asyncio
    async def test_direct_call_returns_error(self):
        """BrowserInspect called directly returns dispatch error."""
        handler = _get_handler("BrowserInspect")
        result = await handler(url="http://example.com", prompt="inspect something")
        assert "must be dispatched" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_dispatch_uses_ephemeral_browser_session(self, tmp_path):
        """BrowserInspect creates and closes an isolated browser scope."""
        from agent.core.workspace import Workspace
        from agent.tool_execution import execute_one_tool

        closed = False

        class FakeBrowserSession:
            async def close(self):
                nonlocal closed
                closed = True

        with (
            patch("agent.tool_execution.BrowserSession", return_value=FakeBrowserSession()),
            patch("agent.tool_execution.set_active_browser_session") as set_active,
            patch("agent.tool_execution.reset_active_browser_session") as reset_active,
            patch("agent.tool_execution.open_url", AsyncMock(return_value="opened")),
            patch("agent.runtime.subagents.run_subagent", AsyncMock(return_value="inspected")),
        ):
            set_active.return_value = "token"
            result = await execute_one_tool(
                {
                    "id": "tc_browser",
                    "function": {
                        "name": "BrowserInspect",
                        "arguments": json.dumps(
                            {
                                "url": "http://example.com",
                                "prompt": "inspect something",
                            }
                        ),
                    },
                },
                Workspace(tmp_path, workspace_uuid="test-workspace"),
                ToolSet(tool_registry, "BrowserInspect"),
                interrupt_event=asyncio.Event(),
                session_id="sid",
            )

        assert result.output == "inspected"
        assert closed
        reset_active.assert_called_once_with("token")

    @pytest.mark.asyncio
    async def test_interrupt_not_supported(self):
        pytest.skip(
            "BrowserInspect tool is dispatched externally, does not support "
            "interrupt_event at handler level"
        )


# ═══════════════════════════════════════════════════════════
# TaskList
# ═══════════════════════════════════════════════════════════


class TestTaskListExecution:
    """TaskList tool — does NOT support interrupt_event."""

    @pytest.mark.asyncio
    async def test_basic_execution(self):
        """TaskList returns current tasks."""
        handler = _get_handler("TaskList")

        ws = MagicMock()
        ws.tasks_path.return_value = Path("/tmp/nonexistent_tasks.json")

        result = await handler(ws=ws, session_id="s1")
        assert "tasks" in result.lower() or "No tasks" in result

    @pytest.mark.asyncio
    async def test_interrupt_not_supported(self):
        pytest.skip("TaskList tool does not support interrupt_event")


# ═══════════════════════════════════════════════════════════
# TaskRewrite
# ═══════════════════════════════════════════════════════════


class TestTaskRewriteExecution:
    """TaskRewrite tool — does NOT support interrupt_event."""

    @pytest.mark.asyncio
    async def test_basic_execution(self, tmp_path):
        """TaskRewrite saves a new task list."""
        handler = _get_handler("TaskRewrite")

        ws = MagicMock()
        tasks_file = tmp_path / "tasks.json"
        ws.tasks_path.return_value = tasks_file

        with patch("agent.tools.task._save_tasks_sync"):
            result = await handler(
                tasks=[
                    {
                        "id": "1",
                        "name": "Test",
                        "description": "A test task",
                        "status": "pending",
                        "depends_on": [],
                        "summary": "",
                    }
                ],
                ws=ws,
                session_id="s1",
            )
            assert "updated" in result.lower() or "Task list" in result

    @pytest.mark.asyncio
    async def test_validation_error(self):
        """TaskRewrite returns error for invalid task list."""
        handler = _get_handler("TaskRewrite")
        ws = MagicMock()

        result = await handler(
            tasks=[{"id": "", "status": "pending"}],
            ws=ws,
            session_id="s1",
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_interrupt_not_supported(self):
        pytest.skip("TaskRewrite tool does not support interrupt_event")


# ═══════════════════════════════════════════════════════════
# TaskUpdate
# ═══════════════════════════════════════════════════════════


class TestTaskUpdateExecution:
    """TaskUpdate tool — does NOT support interrupt_event."""

    @pytest.mark.asyncio
    async def test_basic_execution(self, tmp_path):
        """TaskUpdate updates a single task."""
        handler = _get_handler("TaskUpdate")

        ws = MagicMock()
        tasks_file = tmp_path / "tasks.json"
        # Pre-populate the file so _load_tasks finds it
        import json as _json

        tasks_file.write_text(
            _json.dumps(
                [
                    {
                        "id": "1",
                        "name": "Test",
                        "description": "A test task",
                        "status": "pending",
                        "depends_on": [],
                        "summary": "",
                    }
                ]
            )
        )
        ws.tasks_path.return_value = tasks_file

        with patch("agent.tools.task._save_tasks_sync"):
            result = await handler(
                id="1",
                status="done",
                summary="Completed",
                ws=ws,
                session_id="s1",
            )
            assert "updated" in result.lower() or "Task" in result

    @pytest.mark.asyncio
    async def test_task_not_found(self, tmp_path):
        """TaskUpdate returns error for unknown task id."""
        handler = _get_handler("TaskUpdate")
        ws = MagicMock()
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text("[]")
        ws.tasks_path.return_value = tasks_file

        result = await handler(
            id="nonexistent",
            status="done",
            summary="x",
            ws=ws,
            session_id="s1",
        )
        assert "Error" in result or "does not exist" in result.lower()

    @pytest.mark.asyncio
    async def test_interrupt_not_supported(self):
        pytest.skip("TaskUpdate tool does not support interrupt_event")


# ═══════════════════════════════════════════════════════════
# Cross-cutting: verify execute_one_tool interrupt dispatch
# ═══════════════════════════════════════════════════════════


class TestExecuteOneToolInterrupt:
    """Verify execute_one_tool handles interrupt_event for all tool types."""

    @pytest.mark.asyncio
    async def test_interrupt_before_any_execution(self):
        """execute_one_tool raises InterruptedError if event is set before dispatch."""
        from agent.errors import InterruptedError
        from agent.tool_execution import execute_one_tool

        ws = _make_ws()
        toolset = ToolSet(tool_registry, "Shell")
        interrupt_event = asyncio.Event()
        interrupt_event.set()

        with pytest.raises(InterruptedError, match="Interrupted before tool"):
            await execute_one_tool(
                {"function": {"name": "Shell", "arguments": '{"command":"pwd"}'}},
                ws,
                toolset,
                interrupt_event=interrupt_event,
            )

    @pytest.mark.asyncio
    async def test_unknown_tool_parse_error(self):
        """execute_one_tool returns error for unknown tool name."""
        from agent.tool_execution import execute_one_tool

        ws = _make_ws()
        toolset = ToolSet(tool_registry, "Shell")
        interrupt_event = asyncio.Event()

        result = await execute_one_tool(
            {"function": {"name": "NonexistentTool", "arguments": "{}"}},
            ws,
            toolset,
            interrupt_event=interrupt_event,
        )
        assert "Error" in result
