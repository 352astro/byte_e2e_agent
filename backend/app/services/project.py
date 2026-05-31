"""Project service — global singleton scoped to one workspace directory.

One Project = one workspace = one Scheduler.
All Sessions belong to exactly one Project.
"""

from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.llm import HelloAgentsLLM
from agent.metrics import SQLiteLLMMetricsStore
from agent.sandbox import Sandbox
from agent.scheduler import Scheduler
from agent.session import Session, clear, get_history, load_session
from agent.shadow_repo import ShadowRepo
from agent.tools.task import reconstruct_tasks
from agent.transcript import TranscriptStream
from app.core.config import TMP_DIR

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass
class ActiveStream:
    channel: TranscriptStream
    queue: Any


@dataclass
class SessionStream:
    session: Session
    channel: TranscriptStream | None


class Project:
    """Global singleton per workspace."""

    def __init__(self, workspace: str, metrics_db_path: str) -> None:
        self._workspace = self._normalize(workspace)
        self._sessions: dict[str, Session] = {}  # session_id → Session
        self._scheduler: Scheduler | None = None  # ONE global scheduler
        self._llm: HelloAgentsLLM | None = None
        self._metrics_db_path = metrics_db_path
        metrics_path = Path(metrics_db_path).expanduser()
        if not metrics_path.is_absolute():
            metrics_path = Path(self._workspace) / metrics_path
        self.metrics_store = SQLiteLLMMetricsStore(metrics_path)
        self._shadow_repo: ShadowRepo | None = None

    # ── properties ───────────────────────────────────────

    @property
    def workspace(self) -> str:
        return self._workspace

    @property
    def llm(self) -> HelloAgentsLLM:
        if self._llm is None:
            self._llm = HelloAgentsLLM(metrics_store=self.metrics_store)
        return self._llm

    # ── shadow repo ─────────────────────────────────────

    @property
    def shadow_repo(self) -> ShadowRepo:
        if self._shadow_repo is None:
            repodir = str(Path(self._workspace) / TMP_DIR / ".shadow-vcs")
            self._shadow_repo = ShadowRepo(self._workspace, repodir)
        return self._shadow_repo

    # ── workspace ────────────────────────────────────────

    def set_workspace(self, path: str) -> None:
        resolved = self._normalize(path)
        self._workspace = resolved
        metrics_path = Path(self._metrics_db_path).expanduser()
        if not metrics_path.is_absolute():
            metrics_path = Path(self._workspace) / metrics_path
        self.metrics_store = SQLiteLLMMetricsStore(metrics_path)
        self._shadow_repo: ShadowRepo | None = None
        if self._llm is not None:
            self._llm.metrics_store = self.metrics_store

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
        tmp_dir = Path(self._workspace) / TMP_DIR
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
        # Drop shadow branch (commits), keep workspace untouched
        try:
            self.shadow_repo.delete_branch(session_id)
        except Exception:
            pass
        session_dir = self._session_dir(session_id)
        if session_dir.is_dir():
            shutil.rmtree(session_dir)

    # ── chat / streaming ─────────────────────────────────

    def start_chat(
        self, session_id: str, question: str, max_steps: int
    ) -> ActiveStream:
        session = self.get_session(session_id)
        channel = TranscriptStream()
        queue = channel.subscribe()
        try:
            self.scheduler.start(
                session,
                question,
                channel=channel,
                max_steps=max_steps,
                shadow_repo=self.shadow_repo,
            )
        except RuntimeError:
            channel.unsubscribe(queue)
            raise
        return ActiveStream(channel=channel, queue=queue)

    def get_stream(self, session_id: str) -> SessionStream:
        return SessionStream(
            session=self.get_session(session_id),
            channel=self.scheduler.channel,
        )

    def get_recovery_state(self, session_id: str) -> dict:
        session = self.get_session(session_id)
        scheduler = self.scheduler
        channel = scheduler.channel
        is_running = scheduler.is_running_session(session_id)
        return {
            "transcripts": session.get_transcripts(),
            "running": is_running,
        }

    def get_session_status(self, session_id: str) -> dict:
        self.get_session(session_id)
        return {"running": self.scheduler.is_running_session(session_id)}

    def respond_to_pending(self, transcript_id: str, response: dict) -> None:
        self.scheduler.resolve(transcript_id, response)

    async def interrupt_session(self, session_id: str) -> bool:
        self.get_session(session_id)
        return await self.scheduler.interrupt()

    async def interrupt_current(self) -> bool:
        return await self.scheduler.interrupt()

    def list_commits(self, session_id: str) -> list[dict]:
        self.get_session(session_id)
        return self.shadow_repo.list_commits(session_id)

    def get_commit(self, session_id: str, sha: str) -> dict:
        self.get_session(session_id)
        return self.shadow_repo.get_commit(sha)

    async def checkout_session(self, session_id: str, req: Any) -> dict:
        session = self.get_session(session_id)
        if req.commit_sha:
            try:
                self.shadow_repo.restore(req.commit_sha)
            except KeyError:
                raise KeyError(f"Commit not found: {req.commit_sha}")
        user_content = ""
        if req.truncate_tid:
            for t in session._transcripts:
                if t.id == req.truncate_tid and t.kind == "user_question":
                    user_content = t.message.get("content", "")
                    break
        removed = session.truncate_transcripts_by_tid(
            req.truncate_tid or "", keep=req.keep_tid
        )
        await reconstruct_tasks(session._sandbox, session._transcripts)
        if req.commit_sha:
            try:
                self.shadow_repo.set_head(session_id, req.commit_sha)
            except Exception:
                pass
        return {
            "ok": True,
            "commit_sha": req.commit_sha,
            "removed": removed,
            "user_content": user_content,
        }

    # ── LLM metrics / monitoring ────────────────────────

    def list_llm_calls(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return self.metrics_store.list_calls(
            limit=limit,
            offset=offset,
            session_id=session_id,
        )

    def get_llm_summary(self, session_id: str | None = None) -> dict[str, Any]:
        return self.metrics_store.summary(session_id=session_id)

    def get_llm_dashboard(
        self,
        *,
        limit: int = 20,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return self.metrics_store.dashboard(limit=limit, session_id=session_id)

    # ── scheduler (singleton) ────────────────────────────

    @property
    def scheduler(self) -> Scheduler:
        if self._scheduler is None:
            self._scheduler = Scheduler()
        return self._scheduler

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
