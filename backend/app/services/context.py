"""Workspace-scoped service context.

This is the shared mutable state previously owned by Project: workspace path,
metrics store, shadow repo, and AgentRuntime.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.core.workspace import Workspace as CoreWorkspace
from agent.core.workspace import is_valid_session_id
from agent.hook.logging_hook import LoggingHook
from agent.hook.metrics_hook import MetricsHook
from agent.hook.permission_hook import ToolPermissionHook
from agent.hook.persistence_hook import PersistenceHook
from agent.hook.shadow_commit_hook import ShadowCommitHook
from agent.hook.stream_driver import StreamDriverHook
from agent.llm import get_model_id
from agent.memory import MemoryHook, SQLiteMemoryStore
from agent.metrics import SQLiteLLMMetricsStore
from agent.runtime import AgentRuntime
from agent.session import Session, load_session
from agent.shadow_repo import ShadowRepo
from agent.tools.browser import close_all_browser_sessions_sync
from app.services.errors import AgentBusy
from app.services.workspace_registry import register_workspace
from shared.hooks import HookManager


class WorkspaceContext:
    """One workspace scope shared by all app services."""

    def __init__(
        self,
        workspace: str,
        metrics_db_path: str,
        *,
        _shared_contexts: dict[str, WorkspaceContext] | None = None,
    ) -> None:
        self._workspace = self._normalize(workspace)
        _, self._workspace_uuid = register_workspace(workspace)
        self._metrics_db_path = metrics_db_path
        from app.core.config import get_settings

        self._settings = get_settings()
        self._sessions: dict[str, Session] = {}
        self._runtime: AgentRuntime | None = None
        self._shadow_repo: ShadowRepo | None = None
        self._memory_store: SQLiteMemoryStore | None = None
        self._scoped_contexts = _shared_contexts if _shared_contexts is not None else {}
        self._scoped_contexts[self._workspace] = self
        self._model_id = get_model_id()
        self.metrics_store = self._build_metrics_store()
        self.ensure_storage_ready()

    @property
    def workspace(self) -> str:
        return self._workspace

    @property
    def core_workspace(self) -> CoreWorkspace:
        return CoreWorkspace(self._workspace, workspace_uuid=self._workspace_uuid)

    @property
    def shadow_repo(self) -> ShadowRepo:
        if self._shadow_repo is None:
            self._shadow_repo = ShadowRepo(self.core_workspace)
        return self._shadow_repo

    @property
    def memory_store(self) -> SQLiteMemoryStore:
        if self._memory_store is None:
            self._memory_store = SQLiteMemoryStore(self._workspace_uuid)
        return self._memory_store

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
        if self._any_runtime_busy():
            raise AgentBusy("Cannot switch workspace while an agent task is running")
        from app.core.config import validate_agent_workspace

        resolved = validate_agent_workspace(path)
        close_all_browser_sessions_sync()
        old_workspace = self._workspace
        if self._scoped_contexts.get(old_workspace) is self:
            del self._scoped_contexts[old_workspace]
        self._workspace = self._normalize(resolved)
        _, self._workspace_uuid = register_workspace(resolved)
        self._scoped_contexts[self._workspace] = self
        self._sessions.clear()
        self._runtime = None
        self._shadow_repo = None
        self._memory_store = None
        self.ensure_storage_ready()

    def resolve_workspace(self, path: str | None = None) -> str:
        if path is None or not path.strip():
            return self._workspace
        return self._normalize(path)

    def scoped(self, workspace: str) -> WorkspaceContext:
        resolved = self._normalize(workspace)
        existing = self._scoped_contexts.get(resolved)
        if existing is not None:
            return existing
        return WorkspaceContext(
            resolved,
            self._metrics_db_path,
            _shared_contexts=self._scoped_contexts,
        )

    def any_runtime_running(self) -> bool:
        return self._any_runtime_busy()

    def create_runtime_session_entry(self, session_id: str):
        entry = self.scheduler.get_session(session_id)
        if entry is not None:
            return entry
        config = self._load_session_config(session_id)
        return self.scheduler.create_session(
            config,
            session_id=session_id,
            ws=self.core_workspace,
        )

    def get_session(self, session_id: str) -> Session:
        if not self.messages_path(session_id).is_file():
            raise KeyError(f"Session not found: {session_id}")
        return self.build_session(session_id)

    def get_session_messages(
        self,
        session_id: str,
        *,
        repair: bool = True,
    ) -> list[dict]:
        if not self.messages_path(session_id).is_file():
            raise KeyError(f"Session not found: {session_id}")
        return self.build_session(session_id, repair=repair).get_messages()

    def get_info(self, session_id: str) -> dict[str, Any]:
        if not self.messages_path(session_id).is_file():
            raise KeyError(f"Session not found: {session_id}")
        return {"session_id": session_id, "workspace": self._workspace}

    def pop_session(self, session_id: str) -> Session | None:
        return self._sessions.pop(session_id, None)

    def build_session(self, session_id: str, *, repair: bool = True) -> Session:
        ws = self.core_workspace
        return load_session(session_id, ws=ws, repair=repair)

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
            from app.core.config import PROJECT_ROOT

            metrics_path = PROJECT_ROOT / metrics_path
        return SQLiteLLMMetricsStore(metrics_path)

    def _build_runtime(self) -> AgentRuntime:
        hook_list = [
            StreamDriverHook(),
            MetricsHook(
                self.metrics_store,
                model_id=self._model_id,
                workspace_root=self._workspace,
            ),
            PersistenceHook(self._workspace_uuid),
            ShadowCommitHook(self.shadow_repo),
            ToolPermissionHook(),
        ]
        if self._settings.memory_enabled:
            hook_list.append(
                MemoryHook(
                    self.memory_store,
                    workspace=self._workspace,
                    top_k=self._settings.memory_top_k,
                    recall_top_k=self._settings.memory_recall_top_k,
                    llm_timeout=self._settings.memory_llm_timeout,
                    metrics_store=self.metrics_store,
                )
            )
        hook_list.append(LoggingHook(verbose=True))
        hooks = HookManager(hook_list)
        return AgentRuntime(
            self.core_workspace,
            hooks,
        )

    def _load_session_config(self, session_id: str):
        from agent.core.config import SessionConfig, ToolSetPreset

        raw = self.core_workspace.load_session_config(session_id) or {}
        try:
            tool_set_preset = ToolSetPreset(raw.get("tool_set_preset", "all"))
        except ValueError:
            tool_set_preset = ToolSetPreset.ALL
        return SessionConfig(
            name=str(raw.get("name") or session_id),
            model_id=str(raw.get("model_id") or self._model_id),
            preamble=str(raw.get("preamble") or ""),
            tool_set_preset=tool_set_preset,
            custom_tools=_string_list(raw.get("custom_tools")),
            preloaded_skills=_string_list(raw.get("preloaded_skills")),
            rules=_string_list(raw.get("rules")),
        )

    def _any_runtime_busy(self) -> bool:
        for ctx in set(self._scoped_contexts.values()):
            runtime = ctx._runtime
            if runtime is not None and runtime.status.value != "idle":
                return True
        return False

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


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
