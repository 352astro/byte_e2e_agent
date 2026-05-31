"""Browser 工具 — Playwright 浏览器交互。

BrowserOpen  打开页面，返回 HTML + console 日志。
BrowserAct  点击 / 输入 / 按键，返回新的 HTML + console。
BrowserInspect  启动浏览器子智能体（在 execute_one_tool 中分发）。

设为有头模式：环境变量 BROWSER_HEADLESS=0。默认无头运行。
"""

from __future__ import annotations

import asyncio
import os
from typing import Literal

from langchain_core.tools import StructuredTool
from playwright.async_api import Page
from pydantic import BaseModel, Field

# ── Playwright 单例 ─────────────────────────────────────

_page: Page | None = None
_playwright: Playwright | None = None


def _is_headless() -> bool:
    return os.getenv("BROWSER_HEADLESS", "1").lower() not in ("0", "false", "no")


async def _ensure_browser():
    global _page, _playwright
    if _page is not None:
        try:
            await _page.title()
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

    headless = _is_headless()
    pw = await async_playwright().__aenter__()
    browser = await pw.chromium.launch(headless=headless)
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


# ═══════════════════════════════════════════════════
# BrowserOpen
# ═══════════════════════════════════════════════════


class BrowserOpenInput(BaseModel):
    """BrowserOpen 工具输入参数。"""

    url: str = Field(..., description="URL to open (e.g. http://localhost:5173).")


async def browser_open_handler(url: str, *, ws=None, interrupt_event=None) -> str:
    """Open a URL in the headless browser and return the page HTML + console logs."""
    try:
        page = await _ensure_browser()
    except RuntimeError as exc:
        return str(exc)

    try:
        await page.goto(url, wait_until="networkidle", timeout=15000)
        state = await _capture_state(page)
    except Exception as exc:
        return f"Error navigating to {url}: {exc}"

    lines = [
        f"Title: {state['title']}",
        f"URL: {state['url']}",
        "",
        "── Console ──",
    ]
    lines.extend(state["console"] if state["console"] else ["(empty)"])
    lines.extend(["", "── HTML ──", state["html"]])
    return "\n".join(lines)


browser_open_tool = StructuredTool.from_function(
    coroutine=browser_open_handler,
    name="BrowserOpen",
    description="Open a URL in the headless browser and return the page HTML + console logs.",
    args_schema=BrowserOpenInput,
)


# ═══════════════════════════════════════════════════
# BrowserAct
# ═══════════════════════════════════════════════════


class BrowserActInput(BaseModel):
    """BrowserAct 工具输入参数。"""

    selector: str = Field(..., description="CSS selector of the element to act on.")
    action: Literal["click", "type", "key"] = Field(
        ...,
        description="Action: 'click' to click, 'type' to fill text, 'key' to press a keyboard key.",
    )
    value: str = Field(
        default="",
        description="Text to type (for 'type') or key name (for 'key', e.g. 'Enter', 'Escape').",
    )


async def browser_act_handler(
    selector: str, action: str, value: str = "", *, ws=None, interrupt_event=None
) -> str:
    """Click, type into, or press a key on an element in the browser page."""
    if interrupt_event and interrupt_event.is_set():
        return "[BrowserAct interrupted]"
    page = _page
    if page is None:
        return "Error: Browser not open. Use BrowserOpen first."

    try:
        if action == "click":
            await page.click(selector, timeout=5000)
        elif action == "type":
            await page.fill(selector, value, timeout=5000)
        elif action == "key":
            await page.keyboard.press(value)
        else:
            return f"Error: unknown action '{action}'"

        await asyncio.sleep(0.5)
        state = await _capture_state(page)
    except Exception as exc:
        return f"Error on {action}('{selector}'): {exc}"

    lines = [
        f"After {action}('{selector}'):",
        f"Title: {state['title']}",
        f"URL: {state['url']}",
        "",
        "── Console ──",
    ]
    lines.extend(state["console"] if state["console"] else ["(empty)"])
    lines.extend(["", "── HTML ──", state["html"]])
    return "\n".join(lines)


browser_act_tool = StructuredTool.from_function(
    coroutine=browser_act_handler,
    name="BrowserAct",
    description="Click, type into, or press a key on an element in the browser page.",
    args_schema=BrowserActInput,
)


# ═══════════════════════════════════════════════════
# BrowserInspect
# ═══════════════════════════════════════════════════


class BrowserInspectInput(BaseModel):
    """BrowserInspect 工具输入参数。"""

    max_steps: int = Field(
        default=8,
        ge=1,
        le=20,
        description="Maximum reasoning steps for the inspector sub-agent.",
    )
    prompt: str = Field(
        ...,
        description=(
            "Task for the browser inspector sub-agent. Include the URL "
            "to open and what to look for (e.g. 'Open http://localhost:5173, "
            "check for console errors, verify the Send button exists').\n"
            "\n"
            "CRITICAL: the sub-agent starts with an EMPTY context — it sees "
            "nothing from the parent conversation. You MUST embed ALL relevant "
            "information into this prompt: what code was changed, what the "
            "expected behavior is, which files are involved, any known issues, "
            "and exactly what to inspect. A vague prompt will cause the "
            "sub-agent to miss issues. Be exhaustive."
        ),
    )


async def browser_inspect_handler(**kwargs) -> str:
    """实际执行在 execute_one_tool 中通过名称分发。"""
    return "Error: BrowserInspect must be dispatched via execute_one_tool."


browser_inspect_tool = StructuredTool.from_function(
    coroutine=browser_inspect_handler,
    name="BrowserInspect",
    description="Launch a sub-agent with browser tools to inspect a web page.",
    args_schema=BrowserInspectInput,
)
