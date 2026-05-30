"""临时脚本：有头启动 Playwright 并访问 localhost:5173。

用法:
    cd backend
    uv run python tmp/test_headed_browser.py
"""

import asyncio
import os
import sys

# —— 加载 .env（和 main.py 一致） ——
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")

HEADLESS = os.getenv("BROWSER_HEADLESS", "1").lower() not in ("0", "false", "no")
PORT = int(os.getenv("FRONTEND_PORT", "3000"))
URL = f"http://localhost:{PORT}"

print(f"DISPLAY      = {os.environ.get('DISPLAY', '(not set)')}")
print(f"WAYLAND      = {os.environ.get('WAYLAND_DISPLAY', '(not set)')}")
print(f"BROWSER_HEADLESS env = {os.environ.get('BROWSER_HEADLESS', '(not set)')}")
print(f"HEADLESS     = {HEADLESS}")
print(f"URL          = {URL}")
print()


async def main():
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        print(f"Playwright not installed: {exc}")
        print("Run: uv pip install playwright && playwright install chromium")
        sys.exit(1)

    print("Launching Playwright...")
    pw = await async_playwright().start()

    try:
        print(f"Launching Chromium (headless={HEADLESS})...")
        browser = await pw.chromium.launch(headless=HEADLESS)
        print(f"Browser launched. Version: {browser.version}")
    except Exception as exc:
        print(f"FAILED to launch browser: {exc}")
        print()
        if "executable doesn't exist" in str(exc).lower():
            print("Chromium not installed. Run: playwright install chromium")
        elif "display" in str(exc).lower() or "xdg" in str(exc).lower():
            print("No display available. Try:")
            print("  export DISPLAY=:1")
        sys.exit(1)

    page = await browser.new_page()
    print(f"Navigating to {URL}...")

    try:
        await page.goto(URL, wait_until="networkidle", timeout=15000)
        title = await page.title()
        url = page.url
        print(f"Page loaded: {title}")
        print(f"Final URL:   {url}")
    except Exception as exc:
        print(f"Navigation error: {exc}")
        print("(Browser window should still be visible for inspection)")

    print()
    print("Browser is open. Press Enter to close...")
    await asyncio.get_event_loop().run_in_executor(None, input)

    await browser.close()
    await pw.stop()
    print("Closed.")


if __name__ == "__main__":
    asyncio.run(main())
