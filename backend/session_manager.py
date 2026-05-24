"""SessionManager — runtime cache for workspace-scoped sessions.

Sessions are persisted under:
  workspace/.tmp/{session_id}/

SessionManager keeps only live ReActAgent instances in memory. After a process
restart it rebuilds agents lazily from (workspace, session_id).
"""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from agent.llm import HelloAgentsLLM
from agent.react import ReActAgent
from agent.sandbox import SandBox

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class SessionManager:
    def __init__(self, default_workspace: str) -> None:
        self._default_workspace = self._normalize_workspace(default_workspace)
        self._sessions: dict[tuple[str, str], ReActAgent] = {}
        # shared LLM client across sessions (stateless)
        self._llm: HelloAgentsLLM | None = None

    @property
    def llm(self) -> HelloAgentsLLM:
        if self._llm is None:
            self._llm = HelloAgentsLLM()
        return self._llm

    @property
    def default_workspace(self) -> str:
        return self._default_workspace

    def create(self, workspace: str | None = None) -> dict[str, Any]:
        session_workspace = self._resolve_workspace(workspace)
        session_id = uuid.uuid4().hex[:12]

        messages_path = self._messages_path(session_workspace, session_id)
        messages_path.parent.mkdir(parents=True, exist_ok=True)
        messages_path.touch()
        self._sessions[(session_workspace, session_id)] = self._new_agent(
            session_workspace,
            session_id,
        )
        return self._session_info(session_workspace, session_id)

    def list_info(self, workspace: str | None = None) -> list[dict[str, Any]]:
        session_workspace = self._resolve_workspace(workspace)
        tmp_dir = Path(session_workspace) / ".tmp"
        if not tmp_dir.is_dir():
            return []

        sessions: list[tuple[float, dict[str, Any]]] = []
        for entry in tmp_dir.iterdir():
            if not entry.is_dir() or not self._valid_session_id(entry.name):
                continue
            messages_path = entry / "messages.jsonl"
            if not messages_path.is_file():
                continue
            info = self._session_info(session_workspace, entry.name)
            sessions.append((messages_path.stat().st_mtime, info))

        sessions.sort(key=lambda item: item[0], reverse=True)
        return [info for _, info in sessions]

    def get(self, session_id: str, workspace: str | None = None) -> ReActAgent:
        session_workspace = self._resolve_workspace(workspace)
        key = (session_workspace, session_id)
        if key not in self._sessions:
            if not self._messages_path(session_workspace, session_id).is_file():
                raise KeyError(f"Session not found: {session_id}")
            self._sessions[key] = self._new_agent(session_workspace, session_id)
        return self._sessions[key]

    def get_info(self, session_id: str, workspace: str | None = None) -> dict[str, Any]:
        session_workspace = self._resolve_workspace(workspace)
        if not self._messages_path(session_workspace, session_id).is_file():
            raise KeyError(f"Session not found: {session_id}")
        return self._session_info(session_workspace, session_id)

    def get_history(self, session_id: str, workspace: str | None = None) -> list[dict]:
        return self.get(session_id, workspace).get_history()

    def resolve_workspace(self, workspace: str | None = None) -> str:
        return self._resolve_workspace(workspace)

    async def delete(self, session_id: str, workspace: str | None = None) -> None:
        session_workspace = self._resolve_workspace(workspace)
        agent = self._sessions.pop((session_workspace, session_id), None)
        if agent is not None:
            await agent.clear()

        session_dir = self._session_dir(session_workspace, session_id)
        if session_dir.is_dir():
            shutil.rmtree(session_dir)

    def _new_agent(self, workspace: str, session_id: str) -> ReActAgent:
        sandbox = SandBox(workspace, session_id=session_id)
        return ReActAgent(llm_client=self.llm, sandbox=sandbox, session_id=session_id)

    def _session_dir(self, workspace: str, session_id: str) -> Path:
        if not self._valid_session_id(session_id):
            raise ValueError(f"Invalid session_id: {session_id!r}")
        return Path(workspace) / ".tmp" / session_id

    def _messages_path(self, workspace: str, session_id: str) -> Path:
        return self._session_dir(workspace, session_id) / "messages.jsonl"

    @staticmethod
    def _session_info(workspace: str, session_id: str) -> dict[str, Any]:
        return {"session_id": session_id, "workspace": workspace}

    @staticmethod
    def _valid_session_id(session_id: str) -> bool:
        return bool(_SESSION_ID_RE.fullmatch(session_id))

    def _resolve_workspace(self, workspace: str | None) -> str:
        if workspace is None or not workspace.strip():
            return self._default_workspace
        return self._normalize_workspace(workspace)

    @staticmethod
    def _normalize_workspace(workspace: str) -> str:
        path = Path(workspace).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"Workspace does not exist: {workspace}")
        return str(path)
