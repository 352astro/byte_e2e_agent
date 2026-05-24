"""Transcript — 一等存储单元。

每个 Transcript 代表会话中一个不可分割的事件。
id 贯穿该事件的整个生命周期（chunk/flush/respond 均以此为 key）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TranscriptKind = Literal[
    "user_question",
    "assistant",
    "tool_result",
    "permission_request",
    "permission_response",
    "error",
]


@dataclass
class Transcript:
    """A single event in a session timeline."""

    id: str  # UUID, unique across the session
    kind: TranscriptKind
    message: dict = field(default_factory=dict)
