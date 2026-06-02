from functools import lru_cache

from app.core.config import get_settings
from app.services.chat_service import ChatService
from app.services.checkpoint_service import CheckpointService
from app.services.context import WorkspaceContext
from app.services.metrics_service import MetricsService
from app.services.memory_service import MemoryService
from app.services.settings_service import SettingsService
from app.services.session_service import SessionService
from app.services.workspace_service import WorkspaceService


@lru_cache
def get_context() -> WorkspaceContext:
    settings = get_settings()
    return WorkspaceContext(
        settings.agent_workspace,
        metrics_db_path=settings.llm_metrics_db_path,
    )


def get_workspace_service() -> WorkspaceService:
    return WorkspaceService(get_context())


def get_session_service() -> SessionService:
    return SessionService(get_context())


def get_chat_service() -> ChatService:
    return ChatService(get_context())


def get_checkpoint_service() -> CheckpointService:
    return CheckpointService(get_context())


def get_metrics_service() -> MetricsService:
    return MetricsService(get_context())


def get_memory_service() -> MemoryService:
    return MemoryService(get_context())


def get_settings_service() -> SettingsService:
    return SettingsService(get_context())
