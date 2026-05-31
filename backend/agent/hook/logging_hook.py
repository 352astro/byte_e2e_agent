"""LoggingHook — Rich ANSI terminal output for CLI.

Design:
- ANSI escape codes for color and style; no emoji.
- Content tokens stream via sys.stdout.write + flush, building a natural paragraph.
- Reasoning rendered inline in dim gray, no extra line breaks.
- Structural elements (tool calls, results, turn boundaries) get explicit newlines.
- Suitable for direct terminal viewing or piping (ANSI codes interpreted by terminal).
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from shared.hooks import BaseHook
from shared.types import Message

logger = logging.getLogger(__name__)

# ── ANSI palette ──────────────────────────────────────────

_RST = "\033[0m"
_DIM = "\033[2m"
_BLD = "\033[1m"
_CYN = "\033[36m"
_GRN = "\033[32m"
_RED = "\033[31m"
_YLW = "\033[33m"
_GRY = "\033[90m"
_WHI = "\033[97m"


def _s(text: str, *codes: str) -> str:
    return "".join(codes) + text + _RST


# ── Box-drawing helper ────────────────────────────────────


def _bar(width: int = 60) -> str:
    return _s("\u2500" * width, _GRY)


class LoggingHook(BaseHook):
    """Rich ANSI terminal output.

    Example output::

        You: write a sorting function
        \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        Let me think about this...                  <- normal
        (considering edge cases and performance)     <- dim gray
        Here is a clean implementation.             <- normal, continues inline
        \u2500\u2500\u2500 stop \u2500 in=320 out=150 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

          Shell   {"command": "ls"}                 <- cyan
          OK   total 12                             <- green
        \u2500\u2500\u2500\u2500\u2500\u2500 done \u2500 in=580 out=420 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    """

    def __init__(self, verbose: bool = True) -> None:
        self._verbose = verbose
        self._line_empty = True

    # ═══════════════════════════════════════════════════════
    # BaseHook callbacks
    # ═══════════════════════════════════════════════════════

    async def on_message_start(self, *, msg: Message, **kwargs: Any) -> None:
        pass  # driven by chunk_delta

    async def on_chunk_delta(
        self, *, msg: Message, field: str, delta: str, **kwargs: Any
    ) -> None:
        if not self._verbose:
            return

        if field == "content":
            sys.stdout.write(delta)
            sys.stdout.flush()
            self._line_empty = False

        elif field == "reasoning":
            sys.stdout.write(_s(delta, _DIM))
            sys.stdout.flush()

    async def on_chunk_complete(
        self,
        *,
        msg: Message,
        field: str,
        full_content: str,
        tool_name: str = "",
        tool_args: str = "",
        is_error: bool = False,
        **kwargs: Any,
    ) -> None:
        if not self._verbose:
            return

        if field == "tool_calls":
            self._nl()
            print(f"  {_s(tool_name, _CYN, _BLD)}")
            if tool_args:
                print(_s(f"    {tool_args[:200]}", _GRY))
            self._line_empty = True

        elif field == "tool_result":
            preview = full_content[:300].replace("\n", " ")
            if len(full_content) > 300:
                preview += "..."
            label = "FAIL" if is_error else "OK"
            color = _RED if is_error else _GRN
            print(_s(f"  {label}  {tool_name}: {preview}", color))
            self._line_empty = True

    async def on_message_finish(
        self,
        *,
        msg: Message,
        finish_reason: str = "",
        usage: dict | None = None,
        latency_ms: int = 0,
        **kwargs: Any,
    ) -> None:
        if not self._verbose:
            return
        _usage = usage or {}
        if _usage:
            self._nl()
            parts = [finish_reason]
            pts = _usage.get("prompt_tokens", 0)
            cts = _usage.get("completion_tokens", 0)
            if pts or cts:
                parts.append(f"in={pts} out={cts}")
            if latency_ms:
                parts.append(f"{latency_ms}ms")
            print(
                _s(
                    f"\u2500\u2500\u2500\u2500  {'  '.join(parts)}  \u2500\u2500\u2500\u2500",
                    _GRY,
                )
            )
            self._line_empty = True

    async def on_message_error(
        self, *, msg: Message, error: Exception, **kwargs: Any
    ) -> None:
        self._nl()
        print(_s(f"error: {error}", _RED))
        self._line_empty = True

    # ── Turn ──────────────────────────────────────────────

    async def on_turn_start(self, *, user_question: str = "", **kwargs: Any) -> None:
        if not self._verbose:
            return
        q = user_question[:200]
        print()
        print(_s(f"You: {q}", _YLW, _BLD))
        print(_bar())
        self._line_empty = True

    async def on_turn_end(
        self, *, input_tokens: int = 0, output_tokens: int = 0, **kwargs: Any
    ) -> None:
        if not self._verbose:
            return
        self._nl()
        print(
            _s(
                f"\u2500\u2500\u2500\u2500  done  in={input_tokens} out={output_tokens}  \u2500\u2500\u2500\u2500",
                _GRY,
            )
        )
        self._line_empty = True

    # ── SubAgent ──────────────────────────────────────────

    async def on_subagent_start(
        self, *, task: str = "", max_steps: int = 0, **kwargs: Any
    ) -> None:
        if not self._verbose:
            return
        t = task[:100]
        self._nl()
        print(_s(f"[sub:{max_steps}] {t}", _CYN))
        self._line_empty = True

    async def on_subagent_end(self, *, result: str = "", **kwargs: Any) -> None:
        if not self._verbose:
            return
        r = result[:150]
        print(_s(f"[sub] done: {r}", _GRN))
        self._line_empty = True

    # ── internal ──────────────────────────────────────────

    def _nl(self) -> None:
        if not self._line_empty:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._line_empty = True
