"""Browser 工具 — Playwright 浏览器交互。

BrowserOpen  打开页面，返回 HTML + console 日志。
BrowserAct  点击 / 输入 / 按键，返回新的 HTML + console。
BrowserInspect  启动浏览器子智能体（在 execute_one_tool 中分发）。

设为有头模式：环境变量 BROWSER_HEADLESS=0。默认无头运行。
"""

from __future__ import annotations

import asyncio
import contextlib
from contextvars import ContextVar
from typing import Literal

from langchain_core.tools import StructuredTool
from playwright.async_api import Page, Playwright, async_playwright
from pydantic import BaseModel, Field

# ── Browser session scope ────────────────────────────────


class BrowserSession:
    """One Playwright browser/page lifecycle."""

    def __init__(self) -> None:
        self._page: Page | None = None
        self._playwright = None

    async def ensure_page(self) -> Page:
        if self._page is not None:
            try:
                await self._page.title()
                return self._page
            except Exception:
                self._page = None

        headless = _is_headless()
        self._playwright = await async_playwright().__aenter__()
        browser = await self._playwright.chromium.launch(headless=headless)
        self._page = await browser.new_page()
        return self._page

    async def current_page(self) -> Page | None:
        if self._page is None:
            return None
        try:
            await self._page.title()
            return self._page
        except Exception:
            self._page = None
            return None

    async def close(self) -> None:
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                await self._playwright.__aexit__(None, None, None)
        self._playwright = None
        self._page = None


class BrowserSessionManager:
    """Browser sessions keyed by agent session id."""

    def __init__(self) -> None:
        self._sessions: dict[str, BrowserSession] = {}

    def get(self, session_id: str) -> BrowserSession:
        session = self._sessions.get(session_id)
        if session is None:
            session = BrowserSession()
            self._sessions[session_id] = session
        return session

    def peek(self, session_id: str) -> BrowserSession | None:
        return self._sessions.get(session_id)

    async def close(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await session.close()

    async def close_all(self) -> None:
        sessions = list(self._sessions.values())
        self._sessions.clear()
        await asyncio.gather(
            *(session.close() for session in sessions),
            return_exceptions=True,
        )


_browser_sessions = BrowserSessionManager()

_active_browser_session: ContextVar[BrowserSession | None] = ContextVar(
    "active_browser_session",
    default=None,
)


def set_active_browser_session(session: BrowserSession | None):
    return _active_browser_session.set(session)


def reset_active_browser_session(token) -> None:
    _active_browser_session.reset(token)


async def close_browser_session(session_id: str) -> None:
    await _browser_sessions.close(session_id)


async def close_all_browser_sessions() -> None:
    await _browser_sessions.close_all()
    await _shutdown_browser()


def close_all_browser_sessions_sync() -> None:
    asyncio.run(close_all_browser_sessions())


# ── Legacy global fallback ───────────────────────────────

_page: Page | None = None
_playwright: Playwright | None = None


def _is_headless() -> bool:
    from app.core.config import get_settings

    return get_settings().browser_headless


async def _ensure_browser(session_id: str = ""):
    global _page, _playwright
    scoped_session = _active_browser_session.get()
    if scoped_session is not None:
        return await scoped_session.ensure_page()
    if session_id:
        return await _browser_sessions.get(session_id).ensure_page()

    if _page is not None:
        try:
            await _page.title()
            return _page
        except Exception:
            _page = None

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
        with contextlib.suppress(Exception):
            await _playwright.__aexit__(None, None, None)
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


async def _current_page(session_id: str = "") -> Page | None:
    scoped_session = _active_browser_session.get()
    if scoped_session is not None:
        return await scoped_session.current_page()
    if session_id:
        session = _browser_sessions.peek(session_id)
        return await session.current_page() if session is not None else None
    return _page


async def open_url(url: str, max_bytes: int = 50_000, *, session_id: str = "") -> str:
    """Open a URL in the active browser scope and return page state."""
    try:
        page = await _ensure_browser(session_id=session_id)
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
    return _truncate("\n".join(lines), max_bytes)


def _truncate(text: str, max_bytes: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    truncated = raw[:max_bytes].decode("utf-8", errors="replace")
    return (
        f"{truncated}\n[... truncated at {max_bytes} bytes, {len(raw) - max_bytes} bytes omitted]"
    )


# ═══════════════════════════════════════════════════
# BrowserOpen
# ═══════════════════════════════════════════════════


class BrowserOpenInput(BaseModel):
    """BrowserOpen 工具输入参数。"""

    max_bytes: int = Field(
        default=50_000,
        ge=1000,
        le=500_000,
        description="Maximum UTF-8 bytes to return before truncating.",
    )
    url: str = Field(..., description="URL to open (e.g. http://localhost:5173).")


async def browser_open_handler(
    url: str,
    max_bytes: int = 50_000,
    *,
    ws=None,
    session_id: str = "",
    interrupt_event=None,
) -> str:
    """Open a URL in the headless browser and return the page HTML + console logs."""
    return await open_url(url, max_bytes, session_id=session_id)


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

    max_bytes: int = Field(
        default=50_000,
        ge=1000,
        le=500_000,
        description="Maximum UTF-8 bytes to return before truncating.",
    )
    action: Literal["click", "type", "key"] = Field(
        ...,
        description="Action: 'click' to click, 'type' to fill text, 'key' to press a keyboard key.",
    )
    selector: str = Field(..., description="CSS selector of the element to act on.")
    value: str = Field(
        default="",
        description="Text to type (for 'type') or key name (for 'key', e.g. 'Enter', 'Escape').",
    )


async def browser_act_handler(
    selector: str,
    action: str,
    value: str = "",
    max_bytes: int = 50_000,
    *,
    ws=None,
    session_id: str = "",
    interrupt_event=None,
) -> str:
    """Click, type into, or press a key on an element in the browser page."""
    if interrupt_event and interrupt_event.is_set():
        return "[BrowserAct interrupted]"
    page = await _current_page(session_id=session_id)
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
    return _truncate("\n".join(lines), max_bytes)


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

    url: str = Field(..., description="URL to open before inspection.")
    max_steps: int = Field(
        default=8,
        ge=1,
        le=20,
        description="Maximum reasoning steps for the inspector sub-agent.",
    )
    prompt: str = Field(
        ...,
        description=(
            "Task for the browser inspector sub-agent after the URL is open "
            "(e.g. 'Check for console errors and verify the Send button exists').\n"
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
