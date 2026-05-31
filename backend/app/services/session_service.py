"""Session lifecycle, history, recovery, status, and interrupt."""

from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from typing import Any

from agent.paths import (
    init_session_storage,
    list_sessions as agent_list_sessions,
    messages_path,
)
from agent.session import clear, get_history
from app.services.context import WorkspaceContext
from app.services.workspace_registry import list_workspaces, register_workspace


class SessionService:
    def __init__(self, ctx: WorkspaceContext) -> None:
        self._ctx = ctx

    def create_session(self) -> dict[str, Any]:
        self._ctx.ensure_storage_ready()
        register_workspace(self._ctx.workspace)
        session_id = uuid.uuid4().hex[:12]
        init_session_storage(self._ctx.workspace, session_id)
        self._ctx.put_session(session_id, self._ctx._build_session(session_id))
        return {"session_id": session_id, "workspace": self._ctx.workspace}

    def list_sessions(self) -> list[dict[str, Any]]:
        return self._sessions_for_workspace(self._ctx.workspace)

    def list_all_sessions(self) -> list[dict[str, Any]]:
        workspaces = list_workspaces()
        current = self._ctx.workspace
        if current not in workspaces:
            workspaces = [current, *workspaces]

        combined: list[dict[str, Any]] = []
        for ws in workspaces:
            combined.extend(self._sessions_for_workspace(ws))
        combined.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return combined

    @staticmethod
    def _sessions_for_workspace(workspace: str) -> list[dict[str, Any]]:
        result: list[tuple[float, dict[str, Any]]] = []
        for info in agent_list_sessions(workspace):
            sid = info["session_id"]
            mtime = messages_path(workspace, sid).stat().st_mtime
            result.append(
                (
                    mtime,
                    {
                        **info,
                        "workspace": workspace,
                        "updated_at": datetime.fromtimestamp(
                            mtime, tz=timezone.utc
                        ).isoformat(),
                    },
                )
            )
        result.sort(key=lambda row: row[0], reverse=True)
        return [row[1] for row in result]

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
        session_dir_path = self._ctx.session_dir(session_id)
        if session_dir_path.is_dir():
            shutil.rmtree(session_dir_path)

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
