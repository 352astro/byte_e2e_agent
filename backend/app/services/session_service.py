"""Session lifecycle, history, recovery, status, and interrupt."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from agent.session import clear, get_history
from app.core.config import TMP_DIR
from app.services.context import WorkspaceContext


class SessionService:
    def __init__(self, ctx: WorkspaceContext) -> None:
        self._ctx = ctx

    def create_session(self) -> dict[str, Any]:
        session_id = uuid.uuid4().hex[:12]
        messages_path = self._ctx._messages_path(session_id)
        messages_path.parent.mkdir(parents=True, exist_ok=True)
        messages_path.touch()
        self._ctx.put_session(session_id, self._ctx._build_session(session_id))
        return {"session_id": session_id, "workspace": self._ctx.workspace}

    def list_sessions(self) -> list[dict[str, Any]]:
        tmp_dir = Path(self._ctx.workspace) / TMP_DIR
        if not tmp_dir.is_dir():
            return []
        result: list[tuple[float, dict[str, Any]]] = []
        for entry in tmp_dir.iterdir():
            if not entry.is_dir() or not self._ctx._valid_id(entry.name):
                continue
            if not (entry / "messages.jsonl").is_file():
                continue
            result.append(
                (
                    (entry / "messages.jsonl").stat().st_mtime,
                    {"session_id": entry.name, "workspace": self._ctx.workspace},
                )
            )
        result.sort(key=lambda item: item[0], reverse=True)
        return [info for _, info in result]

    def get_info(self, session_id: str) -> dict[str, Any]:
        return self._ctx.get_info(session_id)

    def get_history(self, session_id: str) -> list[dict]:
        return get_history(self._ctx.get_session(session_id))

    async def delete_session(self, session_id: str) -> None:
        agent = self._ctx.pop_session(session_id)
        if agent is not None:
            await clear(agent)
        try:
            self._ctx.shadow_repo.delete_branch(session_id)
        except Exception:
            pass
        session_dir = self._ctx._session_dir(session_id)
        if session_dir.is_dir():
            shutil.rmtree(session_dir)

    def get_session_status(self, session_id: str) -> dict:
        self._ctx.get_session(session_id)
        return {"running": self._ctx.scheduler.is_running_session(session_id)}

    def get_recovery_state(self, session_id: str) -> dict:
        session = self._ctx.get_session(session_id)
        is_running = self._ctx.scheduler.is_running_session(session_id)
        return {
            "transcripts": session.get_transcripts(),
            "running": is_running,
        }

    async def interrupt_session(self, session_id: str) -> bool:
        self._ctx.get_session(session_id)
        return await self._ctx.scheduler.interrupt()

    async def interrupt_current(self) -> bool:
        return await self._ctx.scheduler.interrupt()
