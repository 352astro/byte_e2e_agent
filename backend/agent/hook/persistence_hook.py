"""PersistenceHook — 将完成的 Message 持久化到 JSONL。

── 职责 ──
- 在 on_message_finish 时将 Message 追加写入 messages.jsonl
- 不侵入主循环，纯 Hook 旁路
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from shared.hooks import BaseHook
from shared.types import Message

logger = logging.getLogger(__name__)


class PersistenceHook(BaseHook):
    """将每个完成的 Message 追加写入 Session 的 JSONL 文件。

    用法:
        hook = PersistenceHook(workspace_uuid="abc123")
        hooks = HookManager([hook, ...])
    """

    def __init__(self, workspace_uuid: str) -> None:
        self._workspace_uuid = workspace_uuid

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
        from agent.paths import messages_path as _msg_path

        return _msg_path(self._workspace_uuid, session_id)

    def _append_message(self, session_id: str, msg: Message) -> None:
        path = self._messages_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = msg.model_dump(mode="json")
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"

        last_exc = None
        for attempt in range(3):
            try:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(line)
                return
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(0.1)
        raise last_exc  # type: ignore[misc]
