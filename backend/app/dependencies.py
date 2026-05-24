from functools import lru_cache

from app.core.config import get_settings
from app.services.project import Project


@lru_cache
def get_project() -> Project:
    settings = get_settings()
    return Project(settings.agent_workspace)
