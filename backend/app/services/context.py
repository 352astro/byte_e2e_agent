"""Workspace-scoped service context.

This is the shared mutable state previously owned by Project: workspace path,
metrics store, shadow repo, and AgentRuntime.
"""

from __future__ import annotations

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
from agent.session import Session, load_session
from agent.shadow_repo import ShadowRepo
from app.services.errors import AgentBusy
from shared.hooks import HookManager


class WorkspaceContext:
    """One workspace scope shared by all app services."""

    def __init__(self, workspace: str, metrics_db_path: str) -> None:
        self._workspace = self._normalize(workspace)
        self._metrics_db_path = metrics_db_path
        self._sessions: dict[str, Session] = {}
        self._runtime: AgentRuntime | None = None
        self._shadow_repo: ShadowRepo | None = None
        self._model_id = get_model_id()
        self.metrics_store = self._build_metrics_store()
        self.ensure_storage_ready()

    @property
    def workspace(self) -> str:
        return self._workspace

    @property
    def core_workspace(self) -> CoreWorkspace:
        return CoreWorkspace(self._workspace)

    @property
    def shadow_repo(self) -> ShadowRepo:
        if self._shadow_repo is None:
            repodir = str(self.core_workspace.agent_dir() / ".shadow-vcs")
            self._shadow_repo = ShadowRepo(self._workspace, repodir)
        return self._shadow_repo

    @property
    def scheduler(self) -> AgentRuntime:
        if self._runtime is None:
            self._runtime = self._build_runtime()
        return self._runtime

    @property
    def stream_driver(self) -> StreamDriverHook:
        for hook in self.scheduler.hooks.hooks:
            if isinstance(hook, StreamDriverHook):
                return hook
        raise RuntimeError("StreamDriverHook not found in HookManager")

    def ensure_storage_ready(self) -> None:
        self.core_workspace.agent_dir().mkdir(parents=True, exist_ok=True)
        metrics_parent = self.metrics_store.db_path.parent
        metrics_parent.mkdir(parents=True, exist_ok=True)
        _probe_writable(metrics_parent, "Metrics storage")
        _probe_writable(self.core_workspace.agent_dir(), "Agent storage")

    def set_workspace(self, path: str) -> None:
        if self._runtime is not None and self._runtime.status.value != "idle":
            raise AgentBusy("Cannot switch workspace while an agent task is running")
        self._workspace = self._normalize(path)
        self.metrics_store = self._build_metrics_store()
        self._sessions.clear()
        self._runtime = None
        self._shadow_repo = None
        self.ensure_storage_ready()

    def resolve_workspace(self, path: str | None = None) -> str:
        if path is None or not path.strip():
            return self._workspace
        return self._normalize(path)

    def create_runtime_session_entry(self, session_id: str):
        from agent.core.config import SessionConfig

        entry = self.scheduler.get_session(session_id)
        if entry is not None:
            return entry
        return self.scheduler.create_session(
            SessionConfig.user_main(name=session_id, model_id=self._model_id),
            session_id=session_id,
            ws=CoreWorkspace(self._workspace),
        )

    def get_session(self, session_id: str) -> Session:
        if not self.messages_path(session_id).is_file():
            raise KeyError(f"Session not found: {session_id}")
        return self.build_session(session_id)

    def get_info(self, session_id: str) -> dict[str, Any]:
        if not self.messages_path(session_id).is_file():
            raise KeyError(f"Session not found: {session_id}")
        return {"session_id": session_id, "workspace": self._workspace}

    def pop_session(self, session_id: str) -> Session | None:
        return self._sessions.pop(session_id, None)

    def build_session(self, session_id: str) -> Session:
        ws = Workspace(self._workspace)
        return load_session(self._workspace, session_id, ws=ws)

    def session_dir(self, session_id: str) -> Path:
        if not self.valid_session_id(session_id):
            raise ValueError(f"Invalid session_id: {session_id!r}")
        return self.core_workspace.session_dir(session_id)

    def messages_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "messages.jsonl"

    def list_session_ids(self) -> list[str]:
        return self.core_workspace.list_session_ids()

    @staticmethod
    def valid_session_id(session_id: str) -> bool:
        return is_valid_session_id(session_id)

    def _build_metrics_store(self) -> SQLiteLLMMetricsStore:
        metrics_path = Path(self._metrics_db_path).expanduser()
        if not metrics_path.is_absolute():
            metrics_path = Path(self._workspace) / metrics_path
        return SQLiteLLMMetricsStore(metrics_path)

    def _build_runtime(self) -> AgentRuntime:
        hooks = HookManager(
            [
                StreamDriverHook(),
                MetricsHook(self.metrics_store, model_id=self._model_id),
                PersistenceHook(self._workspace),
                ShadowCommitHook(self.shadow_repo),
                LoggingHook(verbose=True),
            ]
        )
        return AgentRuntime(CoreWorkspace(self._workspace), hooks)

    @staticmethod
    def _normalize(path: str) -> str:
        p = Path(path).expanduser()
        if not p.is_absolute():
            from app.core.config import PROJECT_ROOT

            p = PROJECT_ROOT / p
        p = p.resolve()
        if not p.is_dir():
            raise ValueError(f"Directory does not exist: {path}")
        return str(p)


def _probe_writable(directory: Path, label: str) -> None:
    probe = directory / ".write_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise ValueError(f"{label} not writable: {directory} ({exc})") from exc
