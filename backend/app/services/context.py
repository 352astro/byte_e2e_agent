"""Shared workspace context — single source of mutable runtime state."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.llm import HelloAgentsLLM
from agent.metrics import SQLiteLLMMetricsStore
from agent.sandbox import Sandbox
from agent.scheduler import Scheduler
from agent.session import Session, load_session
from agent.shadow_repo import ShadowRepo
from app.core.config import TMP_DIR

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class WorkspaceContext:
    """One workspace scope: shared scheduler, session cache, and agent resources."""

    def __init__(self, workspace: str, metrics_db_path: str) -> None:
        self._workspace = self._normalize(workspace)
        self._sessions: dict[str, Session] = {}
        self._scheduler: Scheduler | None = None
        self._llm: HelloAgentsLLM | None = None
        self._metrics_db_path = metrics_db_path
        metrics_path = Path(metrics_db_path).expanduser()
        if not metrics_path.is_absolute():
            metrics_path = Path(self._workspace) / metrics_path
        self.metrics_store = SQLiteLLMMetricsStore(metrics_path)
        self._shadow_repo: ShadowRepo | None = None

    @property
    def workspace(self) -> str:
        return self._workspace

    @property
    def sessions(self) -> dict[str, Session]:
        return self._sessions

    @property
    def llm(self) -> HelloAgentsLLM:
        if self._llm is None:
            self._llm = HelloAgentsLLM(metrics_store=self.metrics_store)
        return self._llm

    @property
    def scheduler(self) -> Scheduler:
        if self._scheduler is None:
            self._scheduler = Scheduler()
        return self._scheduler

    @property
    def shadow_repo(self) -> ShadowRepo:
        if self._shadow_repo is None:
            repodir = str(Path(self._workspace) / TMP_DIR / ".shadow-vcs")
            self._shadow_repo = ShadowRepo(self._workspace, repodir)
        return self._shadow_repo

    def set_workspace(self, path: str) -> None:
        resolved = self._normalize(path)
        self._workspace = resolved
        metrics_path = Path(self._metrics_db_path).expanduser()
        if not metrics_path.is_absolute():
            metrics_path = Path(self._workspace) / metrics_path
        self.metrics_store = SQLiteLLMMetricsStore(metrics_path)
        self._shadow_repo = None
        if self._llm is not None:
            self._llm.metrics_store = self.metrics_store

    def resolve_workspace(self, path: str | None = None) -> str:
        if path is None or not path.strip():
            return self._workspace
        return self._normalize(path)

    def get_session(self, session_id: str) -> Session:
        if session_id not in self._sessions:
            if not self._messages_path(session_id).is_file():
                raise KeyError(f"Session not found: {session_id}")
            self._sessions[session_id] = self._build_session(session_id)
        return self._sessions[session_id]

    def get_info(self, session_id: str) -> dict[str, Any]:
        if not self._messages_path(session_id).is_file():
            raise KeyError(f"Session not found: {session_id}")
        return {"session_id": session_id, "workspace": self._workspace}

    def pop_session(self, session_id: str) -> Session | None:
        return self._sessions.pop(session_id, None)

    def put_session(self, session_id: str, session: Session) -> None:
        self._sessions[session_id] = session

    def _build_session(self, session_id: str) -> Session:
        sandbox = Sandbox(self._workspace, session_id=session_id)
        return load_session(self._workspace, session_id, self.llm, sandbox=sandbox)

    def _session_dir(self, session_id: str) -> Path:
        if not self._valid_id(session_id):
            raise ValueError(f"Invalid session_id: {session_id!r}")
        return Path(self._workspace) / TMP_DIR / session_id

    def _messages_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "messages.jsonl"

    @staticmethod
    def _valid_id(session_id: str) -> bool:
        return bool(_SESSION_ID_RE.fullmatch(session_id))

    @staticmethod
    def _normalize(path: str) -> str:
        p = Path(path).expanduser().resolve()
        if not p.is_dir():
            raise ValueError(f"Directory does not exist: {path}")
        return str(p)
