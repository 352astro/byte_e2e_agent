"""SessionManager — runtime cache for workspace-scoped sessions.

Sessions are persisted by SessionMemory under:
  workspace/.tmp/{session_id}/

SessionManager keeps only live ReActAgent instances in memory. After a process
restart it rebuilds agents lazily from (workspace, session_id).
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from agent.llm import HelloAgentsLLM
from agent.react import ReActAgent
from agent.sandbox import SandBox
from agent.session_memory import SessionMemory


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
        sid = uuid.uuid4().hex[:12]

        memory = SessionMemory(session_workspace, sid)
        memory.ensure()

        self._sessions[(session_workspace, sid)] = self._new_agent(session_workspace, sid)
        return memory.load_meta()

    def list_info(self, workspace: str | None = None) -> list[dict[str, Any]]:
        session_workspace = self._resolve_workspace(workspace)
        return SessionMemory.list_sessions(session_workspace)

    def list_ids(self, workspace: str | None = None) -> list[str]:
        return [item["session_id"] for item in self.list_info(workspace)]

    def get(self, sid: str, workspace: str | None = None) -> ReActAgent:
        session_workspace = self._resolve_workspace(workspace)
        key = (session_workspace, sid)
        if key not in self._sessions:
            memory = SessionMemory(session_workspace, sid)
            if not memory.exists():
                raise KeyError(f"Session not found: {sid}")
            self._sessions[key] = self._new_agent(session_workspace, sid)
        return self._sessions[key]

    def get_info(self, sid: str, workspace: str | None = None) -> dict[str, Any]:
        session_workspace = self._resolve_workspace(workspace)
        memory = SessionMemory(session_workspace, sid)
        if not memory.exists():
            raise KeyError(f"Session not found: {sid}")
        return memory.load_meta()

    def get_history(self, sid: str, workspace: str | None = None) -> list[dict]:
        return self.get(sid, workspace).get_history()

    def resolve_workspace(self, workspace: str | None = None) -> str:
        return self._resolve_workspace(workspace)

    async def delete(self, sid: str, workspace: str | None = None) -> None:
        session_workspace = self._resolve_workspace(workspace)
        agent = self._sessions.pop((session_workspace, sid), None)
        if agent is not None:
            await agent.clear()

        session_dir = Path(session_workspace) / ".tmp" / sid
        if session_dir.is_dir():
            shutil.rmtree(session_dir)

    def _new_agent(self, workspace: str, sid: str) -> ReActAgent:
        sandbox = SandBox(workspace, session_id=sid)
        return ReActAgent(llm_client=self.llm, sandbox=sandbox, session_id=sid)

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
