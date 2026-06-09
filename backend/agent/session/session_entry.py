"""RuntimeSession — single session runtime state.

── 职责 ──
- 持有 SessionTranscript + 运行时状态 + 配置
- 对标 Rust session/entry.rs

── 对标 ──
- Rust: byte_e2e_agent_rs/src/core/session/entry.rs
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.core.config import SessionConfig
from agent.core.workspace import Workspace
from agent.session.session import SessionTranscript, load_session
from agent.session.status import SessionStatus


@dataclass(init=False)
class RuntimeSession:
    """Runtime state and dependencies for one agent session.

    对标 Rust RuntimeSession:
    - id: 唯一标识
    - config: 不可变配置
    - status: 运行时状态
    - 持有 LLM 客户端、Workspace、SessionTranscript
    """

    id: str
    config: SessionConfig
    llm_client: object | None = None  # client or (client, model_id)
    workspace: Workspace
    transcript: SessionTranscript
    status: SessionStatus = SessionStatus.IDLE

    def __init__(
        self,
        id: str,
        config: SessionConfig,
        llm_client: object | None = None,
        workspace: Workspace | None = None,
        transcript: SessionTranscript | None = None,
        status: SessionStatus = SessionStatus.IDLE,
    ) -> None:
        self.id = id
        self.config = config
        self.llm_client = llm_client
        if workspace is None:
            raise ValueError("RuntimeSession requires a workspace")
        self.workspace = workspace
        self.transcript = transcript or load_session(
            id,
            workspace=self.workspace,
            repair=False,
        )
        self.status = status

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
