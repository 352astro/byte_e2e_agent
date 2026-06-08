"""SessionEntry — 单个 Session 的完整运行时聚合。

── 职责 ──
- 持有 Session 数据容器 + 运行时状态 + 配置
- 对标 Rust session/entry.rs

── 对标 ──
- Rust: byte_e2e_agent_rs/src/core/session/entry.rs
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.core.config import SessionConfig
from agent.core.workspace import Workspace
from agent.session.status import SessionStatus


@dataclass
class SessionEntry:
    """单个 Session 的运行时入口。

    对标 Rust SessionEntry:
    - id: 唯一标识
    - config: 不可变配置
    - status: 运行时状态
    - 持有 LLM 客户端、Workspace
    """

    id: str
    config: SessionConfig
    llm_client: object | None = None  # client or (client, model_id)
    ws: Workspace = field(default_factory=Workspace)
    status: SessionStatus = SessionStatus.IDLE

    @property
    def model_id(self) -> str:
        return self.config.model_id

    @property
    def is_idle(self) -> bool:
        return self.status == SessionStatus.IDLE

    @property
    def is_busy(self) -> bool:
        return self.status.is_busy()

    def transition_to(self, new_status: SessionStatus) -> None:
        """状态转换（内部使用）。"""
        self.status = new_status
