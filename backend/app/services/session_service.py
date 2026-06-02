"""Session lifecycle, history, recovery, status, and interrupt."""

from __future__ import annotations

import shutil
import uuid
import json
from datetime import datetime, timezone
from typing import Any

from agent.core.config import SessionConfig
from agent.core.workspace import Workspace as CoreWorkspace
from agent.llm import get_model_id
from agent.session import clear
from app.schemas.session import CreateSessionRequest
from app.services.context import WorkspaceContext
from app.services.errors import SessionNotFound
from app.services.session_scope import (
    SESSION_META_FILE,
    SessionLocator,
    SessionScope,
    read_session_metadata,
    write_session_metadata,
)
from app.services.workspace_registry import list_workspaces, register_workspace


class SessionService:
    def __init__(self, ctx: WorkspaceContext) -> None:
        self._ctx = ctx
        self._locator = SessionLocator(ctx)

    def create_session(self, req: CreateSessionRequest) -> dict[str, Any]:
        self._ctx.ensure_storage_ready()
        register_workspace(self._ctx.workspace)
        session_id = uuid.uuid4().hex[:12]
        messages_path = self._ctx.messages_path(session_id)
        messages_path.parent.mkdir(parents=True, exist_ok=True)
        messages_path.touch()
        config = SessionConfig.user_main(
            name=req.name.strip() or session_id,
            model_id=get_model_id(),
            preamble=req.preamble.strip(),
            preloaded_skills=[
                item.strip() for item in req.preloaded_skills if item.strip()
            ],
            rules=[item.strip() for item in req.rules if item.strip()],
        )
        CoreWorkspace(self._ctx.workspace).save_session_config(session_id, config)
        scope = self._locator.resolve(session_id, workspace_hint=self._ctx.workspace)
        write_session_metadata(scope)
        metadata = read_session_metadata(scope)
        metadata["session_name"] = config.name
        scope.metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
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

    def _sessions_for_workspace(self, workspace: str) -> list[dict[str, Any]]:
        sessions_dir = CoreWorkspace(workspace).sessions_dir()
        if not sessions_dir.is_dir():
            return []
        result: list[tuple[float, dict[str, Any]]] = []
        for entry in sessions_dir.iterdir():
            if not entry.is_dir() or not self._ctx.valid_session_id(entry.name):
                continue
            messages_path = entry / "messages.jsonl"
            if not messages_path.is_file():
                continue
            scope = SessionScope(
                session_id=entry.name,
                workspace=workspace,
                session_dir=entry,
                messages_path=messages_path,
                config_path=entry / "config.json",
                metadata_path=entry / SESSION_META_FILE,
            )
            metadata = read_session_metadata(scope)
            if not metadata:
                write_session_metadata(scope)
                metadata = read_session_metadata(scope)
            session_kind = metadata.get("session_kind") or _session_kind(scope)
            parent_session_id = metadata.get("parent_session_id") or _parent_id(scope)
            mtime = messages_path.stat().st_mtime
            result.append(
                (
                    mtime,
                    {
                        "session_id": entry.name,
                        "workspace": metadata.get("workspace") or workspace,
                        "session_name": metadata.get("session_name", ""),
                        "session_kind": session_kind,
                        "parent_session_id": parent_session_id,
                        "parent_message_id": metadata.get("parent_message_id", ""),
                        "parent_tool_call_id": metadata.get(
                            "parent_tool_call_id", ""
                        ),
                        "updated_at": datetime.fromtimestamp(
                            mtime, tz=timezone.utc
                        ).isoformat(),
                    },
                )
            )
        result.sort(key=lambda row: row[0], reverse=True)
        return [row[1] for row in result]

    def get_info(self, session_id: str) -> dict[str, Any]:
        try:
            scope = self._locator.resolve(session_id)
            return self._ctx.scoped(scope.workspace).get_info(session_id)
        except (KeyError, SessionNotFound) as exc:
            raise SessionNotFound(session_id) from exc

    def get_history(self, session_id: str) -> list[dict]:
        try:
            scope = self._locator.resolve(session_id)
            return (
                self._ctx.scoped(scope.workspace)
                .get_session(session_id)
                .get_messages()
            )
        except (KeyError, SessionNotFound) as exc:
            raise SessionNotFound(session_id) from exc

    async def delete_session(self, session_id: str) -> None:
        scope = self._locator.resolve(session_id)
        ctx = self._ctx.scoped(scope.workspace)
        child_scopes = self._child_scopes(scope.workspace, session_id)
        agent = ctx.pop_session(session_id)
        if agent is not None:
            await clear(agent)
        try:
            ctx.shadow_repo.delete_branch(session_id)
        except Exception:
            pass
        try:
            await ctx.memory_store.delete_session(session_id)
        except Exception:
            pass
        session_dir = ctx.session_dir(session_id)
        if session_dir.is_dir():
            shutil.rmtree(session_dir)
        for child_scope in child_scopes:
            await self.delete_session(child_scope.session_id)

    async def delete_subagents_for_messages(
        self, workspace: str, parent_message_ids: set[str]
    ) -> int:
        if not parent_message_ids:
            return 0
        deleted = 0
        for child_scope in self._child_scopes(workspace):
            metadata = read_session_metadata(child_scope)
            if metadata.get("parent_message_id") not in parent_message_ids:
                continue
            await self.delete_session(child_scope.session_id)
            deleted += 1
        return deleted

    def _child_scopes(
        self, workspace: str, parent_session_id: str | None = None
    ) -> list[SessionScope]:
        sessions_dir = CoreWorkspace(workspace).sessions_dir()
        if not sessions_dir.is_dir():
            return []
        result: list[SessionScope] = []
        for entry in sessions_dir.iterdir():
            if not entry.is_dir() or not self._ctx.valid_session_id(entry.name):
                continue
            scope = SessionScope(
                session_id=entry.name,
                workspace=workspace,
                session_dir=entry,
                messages_path=entry / "messages.jsonl",
                config_path=entry / "config.json",
                metadata_path=entry / SESSION_META_FILE,
            )
            if not scope.messages_path.is_file():
                continue
            if (_session_kind(scope) != "subagent") and (
                read_session_metadata(scope).get("session_kind") != "subagent"
            ):
                continue
            if parent_session_id:
                metadata = read_session_metadata(scope)
                parent_id = metadata.get("parent_session_id") or _parent_id(scope)
                if parent_id != parent_session_id:
                    continue
            result.append(scope)
        return result

    def get_session_status(self, session_id: str) -> dict:
        try:
            scope = self._locator.resolve(session_id)
            ctx = self._ctx.scoped(scope.workspace)
            ctx.get_session(session_id)
        except (KeyError, SessionNotFound) as exc:
            raise SessionNotFound(session_id) from exc
        session_running = ctx.scheduler.is_running_session(session_id)
        return {
            "session_running": session_running,
            "runtime_busy": self._ctx.any_runtime_running(),
        }

    def get_runtime_status(self) -> dict:
        return {"runtime_busy": self._ctx.any_runtime_running()}

    def get_recovery_state(self, session_id: str) -> dict:
        try:
            scope = self._locator.resolve(session_id)
            ctx = self._ctx.scoped(scope.workspace)
            session = ctx.get_session(session_id)
        except (KeyError, SessionNotFound) as exc:
            raise SessionNotFound(session_id) from exc
        runtime = ctx.scheduler
        is_running = runtime.is_running_session(session_id)
        current_msg = runtime.current_message if is_running else None
        return {
            "session": ctx.get_info(session_id),
            "messages": session.get_messages(),
            "session_running": is_running,
            "runtime_busy": self._ctx.any_runtime_running(),
            "current_message": current_msg.model_dump(mode="json")
            if current_msg
            else None,
        }

    async def interrupt_session(self, session_id: str) -> bool:
        try:
            scope = self._locator.resolve(session_id)
            ctx = self._ctx.scoped(scope.workspace)
            ctx.get_session(session_id)
        except (KeyError, SessionNotFound) as exc:
            raise SessionNotFound(session_id) from exc
        return await ctx.scheduler.interrupt()

    async def interrupt_current(self) -> bool:
        return await self._ctx.scheduler.interrupt()


def _load_config(scope: SessionScope) -> dict[str, Any]:
    if not scope.config_path.is_file():
        return {}
    try:
        data = json.loads(scope.config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _parent_id(scope: SessionScope) -> str:
    access = _load_config(scope).get("access", {})
    owner = access.get("owner", {}) if isinstance(access, dict) else {}
    if not isinstance(owner, dict):
        return ""
    if owner.get("kind") != "session":
        return ""
    value = owner.get("session_id")
    return value if isinstance(value, str) else ""


def _session_kind(scope: SessionScope) -> str:
    metadata = read_session_metadata(scope)
    kind = metadata.get("session_kind")
    if isinstance(kind, str) and kind:
        return kind
    access = _load_config(scope).get("access", {})
    if isinstance(access, dict):
        lifecycle = access.get("lifecycle")
        owner = access.get("owner", {})
        if lifecycle == "ephemeral" and isinstance(owner, dict):
            if owner.get("kind") == "session":
                return "subagent"
    return "user"
