"""PersistenceHook — 将完成的 Message 持久化到 JSONL。

── 职责 ──
- 在 on_message_finish 时将 Message 追加写入 messages.jsonl
- 不侵入主循环，纯 Hook 旁路
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from shared.hooks import BaseHook
from shared.types import Message

logger = logging.getLogger(__name__)


class PersistenceHook(BaseHook):
    """将每个完成的 Message 追加写入 Session 的 JSONL 文件。

    用法:
        hook = PersistenceHook(workspace_root="/path/to/project")
        hooks = HookManager([hook, ...])
    """

    def __init__(self, workspace_root: str | Path) -> None:
        self._workspace_root = Path(workspace_root).resolve()

    async def on_message_start(self, *, msg: Message, **kwargs: Any) -> None:
        """Message 开始 — 暂不写盘（等 finish）。"""
        pass

    async def on_message_finish(
        self,
        *,
        msg: Message,
        session_id: str = "",
        **kwargs: Any,
    ) -> None:
        """Message 完成 — 追加写入 JSONL。"""
        if not session_id or not msg.id:
            return

        try:
            self._append_message(session_id, msg)
        except Exception:
            logger.exception("PersistenceHook: failed to persist message %s", msg.id)

    # ── 内部 ────────────────────────────────────────────

    def _messages_path(self, session_id: str) -> Path:
        return (
            self._workspace_root
            / ".byte_agent"
            / "sessions"
            / session_id
            / "messages.jsonl"
        )

    def _append_message(self, session_id: str, msg: Message) -> None:
        path = self._messages_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = msg.model_dump(mode="json")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")
