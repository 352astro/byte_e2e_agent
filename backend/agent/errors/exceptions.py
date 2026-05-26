"""Agent 错误类型。

提供：
- InterruptedError     用户中断异常
- ToolMismatchError    tool 调用/结果不匹配异常
"""

from __future__ import annotations


class InterruptedError(Exception):
    """Raised when the user interrupts the agent loop."""

    pass


class ToolMismatchError(Exception):
    """Raised when LLM detects a tool call / result mismatch."""

    pass
