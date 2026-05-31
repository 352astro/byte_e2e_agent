"""错误处理模块。

提供：
- InterruptedError              中断异常
- ToolMismatchError             tool 调用/结果不匹配异常
- repair_messages               消息修复流水线编排器
- repair_unpaired_tool_calls    修复未配对 tool_call 的流水线环节
"""

from agent.errors.exceptions import InterruptedError, ToolMismatchError
from agent.errors.repair import repair_messages, repair_unpaired_tool_calls

__all__ = [
    "InterruptedError",
    "ToolMismatchError",
    "repair_messages",
    "repair_unpaired_tool_calls",
]
