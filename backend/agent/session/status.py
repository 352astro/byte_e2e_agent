"""Session 运行时状态。

── 状态机 ──
    IDLE ──▶ RUNNING ──▶ IDLE
      │         │
      │         ├──▶ PENDING ──▶ RUNNING
      │         │
      │         └──▶ INTERRUPTED ──▶ IDLE

── 对标 ──
- Rust: byte_e2e_agent_rs/src/core/session/status.rs

── 规则 ──
- 全局同时最多一个 Session 处于 RUNNING 状态
- PENDING: 当前 Session invoke 了另一个 Session，等待其返回
- 严禁修改状态转换逻辑
"""

from __future__ import annotations

from enum import StrEnum


class SessionStatus(StrEnum):
    """单个 Session 的运行时状态。

    对标 Rust SessionStatus。
    """

    IDLE = "idle"  # 空闲，等待被 invoke
    RUNNING = "running"  # 正在执行（全局唯一）
    PENDING = "pending"  # 正在等待另一个 Session 返回
    INTERRUPTED = "interrupted"  # 被中断

    def is_invokable(self) -> bool:
        """是否可被 invoke。"""
        return self == SessionStatus.IDLE

    def is_busy(self) -> bool:
        """是否正在忙碌（RUNNING 或 PENDING）。"""
        return self in (SessionStatus.RUNNING, SessionStatus.PENDING)


class RuntimeStatus(StrEnum):
    """AgentRuntime 全局忙碌状态。

    对标 Rust RuntimeStatus。
    """

    IDLE = "idle"  # 空闲，可以接受 invoke
    RUNNING = "running"  # 某个 Session 正在执行
