#!/usr/bin/env python3
"""CLI entry point -- chat with the agent directly from the terminal.

Usage:
    uv run python cli.py "write a sorting function"   # one-shot
    uv run python cli.py                              # interactive REPL
    AGENT_WORKSPACE=/path/to/project uv run python cli.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))
load_dotenv()

from agent.core.config import SessionConfig  # noqa: E402
from agent.core.workspace import Workspace  # noqa: E402
from agent.hook.logging_hook import LoggingHook  # noqa: E402
from agent.llm import get_model_id  # noqa: E402
from agent.runtime import AgentRuntime  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.services.workspace_registry import register_workspace  # noqa: E402
from shared.hooks import HookManager  # noqa: E402

# ── ANSI ──────────────────────────────────────────────────

_R = "\033[0m"
_B = "\033[1m"
_C = "\033[96m"  # bright cyan
_Y = "\033[93m"  # bright yellow
_K = "\033[90m"

_WIDTH = min(os.get_terminal_size().columns, 80)


def _banner(workspace: str, model: str) -> None:
    w = _short(Path(workspace).name if workspace else ".")
    print()
    print(f" {_C}{_B}Byte E2E Agent{_R}  {_K}CLI{_R}")
    print(f" {_K}workspace{_R} {w}  {_K}model{_R} {model}")
    print(f" {_K}{_hint()}{_R}")
    print(f" {_K}{'\u2500' * (_WIDTH - 2)}{_R}")


def _hint() -> str:
    return "Type your question, or /help, /clear, /quit."


def _short(s: str, n: int = 40) -> str:
    return s if len(s) <= n else s[: n - 3] + "..."


# ═══════════════════════════════════════════════════════════


def _check_env() -> None:
    s = get_settings()
    missing = []
    if not s.llm_api_key:
        missing.append("LLM_API_KEY")
    if not s.llm_base_url:
        missing.append("LLM_BASE_URL")
    if not s.llm_model_id:
        missing.append("LLM_MODEL_ID")
    if missing:
        print(f"Missing env vars: {', '.join(missing)}")
        print("Set them in backend/.env or export in your shell.")
        sys.exit(1)


async def _run_once(ws: Workspace, question: str) -> None:
    hooks = HookManager([LoggingHook(verbose=True)])
    runtime = AgentRuntime(ws, hooks)
    model_id = get_model_id()

    session = runtime.create_session(
        SessionConfig.user_main(name="cli", model_id=model_id),
    )
    _banner(str(ws.root), model_id)

    await runtime.invoke_user(session, question)
    if runtime._loop_task is not None:
        try:
            await runtime._loop_task
        except Exception:
            pass


async def _run_repl(ws: Workspace) -> None:
    hooks = HookManager([LoggingHook(verbose=True)])
    runtime = AgentRuntime(ws, hooks)
    model_id = get_model_id()

    session = runtime.create_session(
        SessionConfig.user_main(name="cli", model_id=model_id),
    )
    _banner(str(ws.root), model_id)

    while True:
        try:
            q = input().strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not q:
            continue

        if q in ("/q", "/quit", "/exit"):
            break
        if q == "/help":
            print(_hint())
            continue
        if q == "/clear":
            session = runtime.create_session(
                SessionConfig.user_main(name="cli", model_id=model_id),
            )
            print(f"{_K}  (new session){_R}")
            continue

        try:
            await runtime.invoke_user(session, q)
            if runtime._loop_task is not None:
                await runtime._loop_task
        except RuntimeError as exc:
            print(f"{_K}error: {exc}{_R}")
        except KeyboardInterrupt:
            await runtime.interrupt()
            print()


# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    _check_env()

    settings = get_settings()
    workspace = settings.agent_workspace or os.getcwd()
    _, ws_uuid = register_workspace(workspace)
    args = sys.argv[1:]

    ws = Workspace(workspace, workspace_uuid=ws_uuid)
    if args:
        asyncio.run(_run_once(ws, " ".join(args)))
    else:
        asyncio.run(_run_repl(ws))
