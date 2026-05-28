"""PyRepl 工具 — 安全受限的 Python 表达式求值器。

快速计算 / 数据处理，不支持中断和流式输出。
"""

from __future__ import annotations

import io
import sys
import traceback

from pydantic import Field

from agent.tools.base import BaseTool

# ── 安全内置白名单 ──────────────────────────────────────
# 只暴露纯计算和数据结构操作，封死 I/O、反射、导入。
_SAFE_BUILTINS: dict[str, object] = {
    # 核心
    "print": print,
    "len": len,
    "range": range,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "bytes": bytes,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "frozenset": frozenset,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "sorted": sorted,
    "reversed": reversed,
    "iter": iter,
    "next": next,
    "slice": slice,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "round": round,
    "pow": pow,
    "divmod": divmod,
    "ord": ord,
    "chr": chr,
    "repr": repr,
    "hash": hash,
    "id": id,
    "type": type,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "callable": callable,
    "hasattr": hasattr,
    "all": all,
    "any": any,
    # 异常
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "StopIteration": StopIteration,
    # 常量
    "True": True,
    "False": False,
    "None": None,
}

# ── 输出上限 ────────────────────────────────────────────

_MAX_OUTPUT_BYTES = 10_240  # 10 KiB


class PyRepl(BaseTool):
    """Run a snippet of Python code in a safe sandbox and return output."""

    code: str = Field(
        ...,
        description=(
            "Python code to execute. The sandbox exposes print() and basic "
            "builtins (int, str, list, dict, sorted, zip, ...).  I/O and "
            "imports are blocked."
        ),
    )

    async def execute(self, *, sandbox=None, channel=None, interrupt_event=None, scheduler=None, toolset=None, result_id="") -> str:
        stdout = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = stdout

        try:
            compiled = compile(self.code, "<pyrepl>", "exec")
        except SyntaxError as exc:
            return f"SyntaxError: {exc}"

        try:
            exec(compiled, {"__builtins__": _SAFE_BUILTINS})
        except Exception:
            return traceback.format_exc().strip()
        finally:
            sys.stdout = old_stdout

        output = stdout.getvalue()
        if len(output) > _MAX_OUTPUT_BYTES:
            output = (
                output[:_MAX_OUTPUT_BYTES]
                + f"\n\n[Output truncated at {_MAX_OUTPUT_BYTES} bytes]"
            )
        return output if output else "(no output)"
