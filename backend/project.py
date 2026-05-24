"""Project — global singleton scoped to one workspace directory.

One Project = one workspace = one Scheduler.
All Sessions belong to exactly one Project.
"""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Any

import agent.session_memory as session_memory
from agent.llm import HelloAgentsLLM
from agent.sandbox import SandBox
from agent.scheduler import Scheduler
from agent.session import Session, clear, get_history

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class Project:
    """Global singleton per workspace."""

    def __init__(self, workspace: str) -> None:
        self._workspace = self._normalize(workspace)
        self._sessions: dict[str, Session] = {}  # session_id → Session
        self._scheduler: Scheduler | None = None  # ONE global scheduler
        self._llm: HelloAgentsLLM | None = None

    # ── properties ───────────────────────────────────────

    @property
    def workspace(self) -> str:
        return self._workspace

    @property
    def llm(self) -> HelloAgentsLLM:
        if self._llm is None:
            self._llm = HelloAgentsLLM()
        return self._llm

    # ── workspace ────────────────────────────────────────

    def set_workspace(self, path: str) -> None:
        resolved = self._normalize(path)
        self._workspace = resolved

    def resolve_workspace(self, path: str | None = None) -> str:
        if path is None or not path.strip():
            return self._workspace
        return self._normalize(path)

    # ── sessions ─────────────────────────────────────────

    def create_session(self) -> dict[str, Any]:
        session_id = uuid.uuid4().hex[:12]
        messages_path = self._messages_path(session_id)
        messages_path.parent.mkdir(parents=True, exist_ok=True)
        messages_path.touch()
        self._sessions[session_id] = self._build_session(session_id)
        return {"session_id": session_id, "workspace": self._workspace}

    def list_sessions(self) -> list[dict[str, Any]]:
        tmp_dir = Path(self._workspace) / ".tmp"
        if not tmp_dir.is_dir():
            return []
        result: list[tuple[float, dict[str, Any]]] = []
        for entry in tmp_dir.iterdir():
            if not entry.is_dir() or not self._valid_id(entry.name):
                continue
            if not (entry / "messages.jsonl").is_file():
                continue
            result.append(
                (
                    (entry / "messages.jsonl").stat().st_mtime,
                    {"session_id": entry.name, "workspace": self._workspace},
                )
            )
        result.sort(key=lambda item: item[0], reverse=True)
        return [info for _, info in result]

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

    def get_history(self, session_id: str) -> list[dict]:
        return get_history(self.get_session(session_id))

    async def delete_session(self, session_id: str) -> None:
        agent = self._sessions.pop(session_id, None)
        if agent is not None:
            await clear(agent)
        session_dir = self._session_dir(session_id)
        if session_dir.is_dir():
            shutil.rmtree(session_dir)

    # ── scheduler (singleton) ────────────────────────────

    @property
    def scheduler(self) -> Scheduler:
        if self._scheduler is None:
            self._scheduler = Scheduler()
        return self._scheduler

    def _build_session(self, session_id: str) -> Session:
        sandbox = SandBox(self._workspace, session_id=session_id)
        return session_memory.load_session(
            self._workspace, session_id, self.llm, sandbox=sandbox
        )

    def _session_dir(self, session_id: str) -> Path:
        if not self._valid_id(session_id):
            raise ValueError(f"Invalid session_id: {session_id!r}")
        return Path(self._workspace) / ".tmp" / session_id

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
