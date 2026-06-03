"""Structured tool handler result.

Tools may return plain strings for backward compatibility.  When a tool knows
the execution semantics, it can return ToolResult so runtime can surface status
without scraping output text.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolResult:
    output: str
    status: str = "success"
    source: str = "tool"
    reason: str = ""

    def __str__(self) -> str:
        return self.output

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.output == other
        return super().__eq__(other)

    def __contains__(self, item: object) -> bool:
        return str(item) in self.output

    def __getattr__(self, name: str):
        return getattr(self.output, name)
