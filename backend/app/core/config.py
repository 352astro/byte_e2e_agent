import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env")
load_dotenv()

# Central constant for the agent's internal storage directory.
# TMP_DIR is kept as a compatibility alias for older imports.
AGENT_DIR = ".byte_agent"
TMP_DIR = AGENT_DIR

DEFAULT_LLM_METRICS_DB_PATH = f"{AGENT_DIR}/metrics.db"


def resolve_agent_workspace(path: str) -> str:
    """Resolve workspace path; relative paths are anchored at PROJECT_ROOT."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return str(p.resolve())


@dataclass(frozen=True)
class Settings:
    app_title: str
    agent_workspace: str
    cors_allow_origins: tuple[str, ...]
    cors_allow_origin_regex: str
    cors_allow_credentials: bool
    llm_metrics_db_path: str
    memory_enabled: bool
    memory_top_k: int
    memory_recall_top_k: int
    memory_llm_timeout: float


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_title="Byte E2E Agent Backend",
        agent_workspace=resolve_agent_workspace(
            os.environ.get("AGENT_WORKSPACE", str(PROJECT_ROOT))
        ),
        cors_allow_origins=("http://localhost:5173",),
        cors_allow_origin_regex=r"http://localhost:\d+",
        cors_allow_credentials=True,
        llm_metrics_db_path=(
            os.environ.get("LLM_METRICS_DB_PATH") or DEFAULT_LLM_METRICS_DB_PATH
        ),
        memory_enabled=_env_bool("MEMORY_ENABLED", default=False),
        memory_top_k=_env_int("MEMORY_TOP_K", default=5),
        memory_recall_top_k=_env_int("MEMORY_RECALL_TOP_K", default=30),
        memory_llm_timeout=_env_float("MEMORY_LLM_TIMEOUT", default=10.0),
    )


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, *, default: int) -> int:
    try:
        return int(os.environ.get(name, ""))
    except ValueError:
        return default


def _env_float(name: str, *, default: float) -> float:
    try:
        return float(os.environ.get(name, ""))
    except ValueError:
        return default
