"""Turn — 一轮对话的规范化快照，_turns 与前端共用的前置模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ToolStep:
    name: str
    arguments: dict
    result: str | None = None  # None = 尚未执行（流式中）


@dataclass
class Turn:
    role: Literal["user", "assistant"]
    # user
    question: str = ""
    # assistant
    reasoning: str = ""
    content: str = ""
    tool_calls: list[ToolStep] = field(default_factory=list)
    finish_answer: str | None = None
