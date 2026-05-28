"""Browser 工具 — Playwright 浏览器交互。

BrowserOpen  打开页面，返回 HTML + console 日志。
BrowserAct  点击 / 输入 / 按键，返回新的 HTML + console。
"""

from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import Field

from agent.tools.base import BaseTool
from agent.tools.glob import Glob
from agent.tools.grep import Grep
from agent.tools.read import Read
from agent.tools.shell import Shell
from agent.tools.toolset import ToolSet

# ── Playwright 单例 ─────────────────────────────────────

_page: object | None = None
_playwright: object | None = None


async def _ensure_browser():
    global _page, _playwright
    if _page is not None:
        try:
            await _page.title()  # probe if still alive
            return _page
        except Exception:
            _page = None

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright not installed. Run: pip install playwright && "
            "playwright install chromium"
        )

    pw = await async_playwright().__aenter__()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()
    _playwright = pw
    _page = page
    return page


async def _shutdown_browser():
    global _page, _playwright
    if _playwright is not None:
        try:
            await _playwright.__aexit__(None, None, None)
        except Exception:
            pass
        _playwright = None
        _page = None


async def _capture_state(page, *, with_html: bool = True) -> dict:
    """Grab console + HTML from the page."""
    console: list[str] = []

    def _on_console(msg):
        entry = f"[{msg.type}] {msg.text}"
        loc = msg.location
        if loc and loc.get("url", ""):
            entry += f"  ({loc['url']}:{loc.get('lineNumber', '?')})"
        console.append(entry)

    page.on("console", _on_console)

    result: dict = {}
    if with_html:
        try:
            html = await page.content()
            result["html"] = html
        except Exception:
            result["html"] = "(unable to read HTML)"

    result["url"] = page.url
    try:
        result["title"] = await page.title()
    except Exception:
        result["title"] = ""
    result["console"] = console
    return result


# ── Tools ────────────────────────────────────────────────


class BrowserOpen(BaseTool):
    """Open a URL in the headless browser and return the page HTML + console logs."""

    url: str = Field(..., description="URL to open (e.g. http://localhost:5173).")

    async def execute(
        self,
        *,
        sandbox=None,
        channel=None,
        interrupt_event=None,
        scheduler=None,
        toolset=None,
        result_id: str = "",
    ) -> str:
        try:
            page = await _ensure_browser()
        except RuntimeError as exc:
            return str(exc)

        try:
            await page.goto(self.url, wait_until="networkidle", timeout=15000)
            state = await _capture_state(page)
        except Exception as exc:
            return f"Error navigating to {self.url}: {exc}"

        lines = [
            f"Title: {state['title']}",
            f"URL: {state['url']}",
            "",
            "── Console ──",
        ]
        lines.extend(state["console"] if state["console"] else ["(empty)"])
        lines.extend(["", "── HTML ──", state["html"]])
        return "\n".join(lines)


class BrowserAct(BaseTool):
    """Click, type into, or press a key on an element in the browser page."""

    selector: str = Field(..., description="CSS selector of the element to act on.")
    action: Literal["click", "type", "key"] = Field(
        ...,
        description="Action: 'click' to click, 'type' to fill text, 'key' to press a keyboard key.",
    )
    value: str = Field(
        default="",
        description="Text to type (for 'type') or key name (for 'key', e.g. 'Enter', 'Escape').",
    )

    async def execute(
        self,
        *,
        sandbox=None,
        channel=None,
        interrupt_event=None,
        scheduler=None,
        toolset=None,
        result_id: str = "",
    ) -> str:
        page = _page
        if page is None:
            return "Error: Browser not open. Use BrowserOpen first."

        try:
            if self.action == "click":
                await page.click(self.selector, timeout=5000)
            elif self.action == "type":
                await page.fill(self.selector, self.value, timeout=5000)
            elif self.action == "key":
                await page.keyboard.press(self.value)
            else:
                return f"Error: unknown action '{self.action}'"

            # Wait for any navigation / rendering
            await asyncio.sleep(0.5)
            state = await _capture_state(page)
        except Exception as exc:
            return f"Error on {self.action}('{self.selector}'): {exc}"

        lines = [
            f"After {self.action}('{self.selector}'):",
            f"Title: {state['title']}",
            f"URL: {state['url']}",
            "",
            "── Console ──",
        ]
        lines.extend(state["console"] if state["console"] else ["(empty)"])
        lines.extend(["", "── HTML ──", state["html"]])
        return "\n".join(lines)


class BrowserInspect(BaseTool):
    """Launch a sub-agent with browser and file tools to inspect a web page.

    The sub-agent can open URLs, click elements, and read source files.
    It reports back findings, console errors, and DOM analysis.
    """

    prompt: str = Field(
        ...,
        description=(
            "Task for the browser inspector sub-agent.  Include the URL "
            "to open and what to look for (e.g. 'Open http://localhost:5173, "
            "check for console errors, verify the Send button exists')."
        ),
    )
    max_steps: int = Field(
        default=8,
        ge=1,
        le=20,
        description="Maximum reasoning steps for the inspector sub-agent.",
    )
    fork: bool = Field(
        default=True,
        description=(
            "If True, the sub-agent inherits the full parent conversation "
            "history. Strongly recommended for browser inspection — the "
            "sub-agent needs context about what code has been changed."
        ),
    )

    async def execute(
        self,
        *,
        sandbox=None,
        channel=None,
        interrupt_event=None,
        scheduler=None,
        toolset=None,
        result_id: str = "",
    ) -> str:
        run = getattr(scheduler, "_run_subagent", None)
        if run is None:
            return "Error: BrowserInspect requires scheduler reference."

        browser_toolset = ToolSet([BrowserOpen, BrowserAct, Read, Grep, Glob, Shell])
        return await run(
            sandbox, browser_toolset, channel,
            self.prompt, self.max_steps,
            fork=self.fork,
        )
