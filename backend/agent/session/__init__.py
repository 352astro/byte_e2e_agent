"""session 包 — Session 配置 / 状态 / 入口。

向后兼容：from agent.session import Session 依然有效。
"""

from agent.core.config import SessionConfig
from agent.session._data import (
    Session,
    _default_toolset,
    _load_messages,
    _messages_path,
    _session_dir,
    _validate_session_id,
    clear,
    get_history,
    load_session,
)
from agent.session.entry import SessionEntry
from agent.session.status import RuntimeStatus, SessionStatus

__all__ = [
    "Session",
    "clear",
    "get_history",
    "load_session",
    "RuntimeStatus",
    "SessionConfig",
    "SessionEntry",
    "SessionStatus",
]
