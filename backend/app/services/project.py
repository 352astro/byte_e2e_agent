"""Project service — global singleton scoped to one workspace directory.

One Project = one workspace = one AgentRuntime.
All Sessions belong to exactly one Project.

v2: LangChain ChatOpenAI + HookManager(StreamDriver, Metrics, Logging) + AgentRuntime
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.core.workspace import Workspace, is_valid_session_id
from agent.core.workspace import Workspace as CoreWorkspace
from agent.hook.logging_hook import LoggingHook
from agent.hook.metrics_hook import MetricsHook
from agent.hook.persistence_hook import PersistenceHook
from agent.hook.shadow_commit_hook import ShadowCommitHook
from agent.hook.stream_driver import StreamDriverHook
from agent.llm import get_model_id
from agent.metrics import SQLiteLLMMetricsStore
from agent.runtime import AgentRuntime
from agent.session import Session, clear, load_session
from agent.shadow_repo import ShadowRepo
from shared.hooks import HookManager
from shared.types import StreamEvent


@dataclass
class ActiveStream:
    driver: StreamDriverHook
    queue: "asyncio.Queue[StreamEvent | None]"


@dataclass
class SessionStream:
    session: Session
    driver: StreamDriverHook | None


class Project:
    """Global singleton per workspace."""

    def __init__(self, workspace: str, metrics_db_path: str) -> None:
        self._workspace = self._normalize(workspace)
        self._sessions: dict[str, Session] = {}
        self._metrics_db_path = metrics_db_path

        # ── Metrics store ────────────────────────────
        metrics_path = Path(metrics_db_path).expanduser()
        if not metrics_path.is_absolute():
            metrics_path = Path(self._workspace) / metrics_path
        self.metrics_store = SQLiteLLMMetricsStore(metrics_path)

        # ── Runtime (lazy) ────────────────────────────
        self._runtime: AgentRuntime | None = None
        self._shadow_repo: ShadowRepo | None = None
        self._model_id = get_model_id()

    # ── properties ───────────────────────────────────────

    @property
    def workspace(self) -> str:
        return self._workspace

    # ── shadow repo ─────────────────────────────────────

    @property
    def shadow_repo(self) -> ShadowRepo:
        if self._shadow_repo is None:
            repodir = str(CoreWorkspace(self._workspace).agent_dir() / ".shadow-vcs")
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
        self._shadow_repo = None
        # Reset runtime to pick up new workspace
        self._runtime = None

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
        return {"session_id": session_id, "workspace": self._workspace}

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions_dir = CoreWorkspace(self._workspace).sessions_dir()
        if not sessions_dir.is_dir():
            return []
        result: list[tuple[float, dict[str, Any]]] = []
        for entry in sessions_dir.iterdir():
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
        """Get or build a Session, always reloading messages from disk.

        The runtime's PersistenceHook writes messages to JSONL asynchronously,
        so the in-memory cache is never up-to-date. We rebuild from disk on
        every access to guarantee the caller sees the latest messages.
        """
        if not self._messages_path(session_id).is_file():
            raise KeyError(f"Session not found: {session_id}")
        return self._build_session(session_id)

    def get_info(self, session_id: str) -> dict[str, Any]:
        if not self._messages_path(session_id).is_file():
            raise KeyError(f"Session not found: {session_id}")
        return {"session_id": session_id, "workspace": self._workspace}

    def get_history(self, session_id: str) -> list[dict]:
        return self.get_session(session_id).get_messages()

    async def delete_session(self, session_id: str) -> None:
        agent = self._sessions.pop(session_id, None)
        if agent is not None:
            await clear(agent)
        try:
            self.shadow_repo.delete_branch(session_id)
        except Exception:
            pass
        session_dir = self._session_dir(session_id)
        if session_dir.is_dir():
            shutil.rmtree(session_dir)

    # ── chat / streaming ─────────────────────────────────

    @property
    def stream_driver(self) -> StreamDriverHook:
        """获取 StreamDriverHook（从 HookManager 中查找）。"""
        for h in self.scheduler.hooks.hooks:
            if isinstance(h, StreamDriverHook):
                return h
        raise RuntimeError("StreamDriverHook not found in HookManager")

    def start_chat(
        self, session_id: str, question: str, max_steps: int
    ) -> ActiveStream:
        """启动执行，返回 ActiveStream（driver + queue）供 SSE 消费。

        subscribe-before-start: driver 先订阅，再启动 runtime。
        """
        session = self.get_session(session_id)
        driver = self.stream_driver
        queue = driver.subscribe(session_id)

        # 获取或创建 SessionEntry
        entry = self.scheduler.get_session(session_id)
        if entry is None:
            from agent.core.config import SessionConfig
            from agent.core.workspace import Workspace as CoreWorkspace

            entry = self.scheduler.create_session(
                SessionConfig.user_main(name=session_id, model_id=self._model_id),
                session_id=session_id,
                ws=CoreWorkspace(self._workspace),
            )

        try:
            self.scheduler.start(
                entry,
                question,
                max_steps=max_steps,
            )
        except RuntimeError:
            driver.unsubscribe(queue)
            raise
        return ActiveStream(driver=driver, queue=queue)

    def get_stream(self, session_id: str) -> SessionStream:
        return SessionStream(
            session=self.get_session(session_id),
            driver=self.stream_driver,
        )

    def get_recovery_state(self, session_id: str) -> dict:
        session = self.get_session(session_id)
        runtime = self.scheduler
        is_running = runtime.is_running_session(session_id)
        current_msg = runtime.current_message if is_running else None
        return {
            "session": {"session_id": session_id},
            "messages": session.get_messages(),
            "running": is_running,
            "current_message": current_msg.model_dump(mode="json")
            if current_msg
            else None,
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

    # ── runtime / scheduler ──────────────────────────────

    @property
    def scheduler(self) -> AgentRuntime:
        """全局 AgentRuntime（兼容旧 scheduler 属性名）。

        AgentRuntime 内部自行管理 openai client 的懒加载。
        """
        if self._runtime is None:
            self._runtime = self._build_runtime()
        return self._runtime

    def _build_runtime(self) -> AgentRuntime:
        """构建 AgentRuntime，注入 LLM + Hooks。"""
        hooks = HookManager(
            [
                StreamDriverHook(),
                MetricsHook(self.metrics_store, model_id=self._model_id),
                PersistenceHook(self._workspace),
                ShadowCommitHook(self.shadow_repo),
                LoggingHook(verbose=True),
            ]
        )
        ws = CoreWorkspace(self._workspace)
        return AgentRuntime(ws, hooks)

    # ── internal ─────────────────────────────────────────

    def _build_session(self, session_id: str) -> Session:
        ws = Workspace(self._workspace)
        return load_session(self._workspace, session_id, ws=ws)

    def _session_dir(self, session_id: str) -> Path:
        if not self._valid_id(session_id):
            raise ValueError(f"Invalid session_id: {session_id!r}")
        return CoreWorkspace(self._workspace).session_dir(session_id)

    def _messages_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "messages.jsonl"

    @staticmethod
    def _valid_id(session_id: str) -> bool:
        return is_valid_session_id(session_id)

    @staticmethod
    def _normalize(path: str) -> str:
        p = Path(path).expanduser().resolve()
        if not p.is_dir():
            raise ValueError(f"Directory does not exist: {path}")
        return str(p)
