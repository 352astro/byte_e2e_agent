"""Project-wide configuration — single source of truth for all env vars.

Usage:
    from app.core.config import get_settings
    settings = get_settings()
    print(settings.llm_api_key)
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env")
load_dotenv()

# Central constant for the agent's internal storage directory
# (under PROJECT_ROOT).
AGENT_DATA_DIR = ".byte_agent"
AGENT_PLAYGROUND_DIR = ".agent-playground"

DEFAULT_LLM_METRICS_DB_PATH = f"{AGENT_DATA_DIR}/metrics.db"


def _paths_overlap(left: Path, right: Path) -> bool:
    try:
        left.relative_to(right)
        return True
    except ValueError:
        pass
    try:
        right.relative_to(left)
        return True
    except ValueError:
        return False


def resolve_agent_workspace(path: str) -> str:
    """Resolve workspace path; relative paths are anchored at PROJECT_ROOT."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return str(p.resolve())


def playground_workspace() -> str:
    """Return the repo-local ignored playground workspace path."""
    path = PROJECT_ROOT / AGENT_PLAYGROUND_DIR
    path.mkdir(parents=True, exist_ok=True)
    return str(path.resolve())


def coerce_agent_workspace(path: str | Path) -> str:
    """Normalize workspace and redirect repo paths to the local playground."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    resolved = p.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
        return playground_workspace()
    except ValueError:
        return str(resolved)


def validate_agent_workspace(path: str | Path) -> str:
    """Return a resolved workspace path after enforcing global safety policy."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    resolved = p.resolve()
    if resolved == Path(playground_workspace()).resolve():
        return str(resolved)
    try:
        PROJECT_ROOT.relative_to(resolved)
        raise ValueError(f"Workspace cannot contain the application repository: {resolved}")
    except ValueError as exc:
        if "Workspace cannot" in str(exc):
            raise
    if _paths_overlap(resolved, PROJECT_ROOT):
        raise ValueError(
            "Workspace cannot be the application repository, contain it, "
            f"or be inside it: {resolved}"
        )
    return str(resolved)


def _default_agent_workspace() -> str:
    """Create and return a safe default workspace outside PROJECT_ROOT."""
    return playground_workspace()


@dataclass(frozen=True)
class Settings:
    # ── App ──────────────────────────────────────────
    app_title: str
    agent_workspace: str
    cors_allow_origins: tuple[str, ...]
    cors_allow_origin_regex: str
    cors_allow_credentials: bool

    # ── LLM ──────────────────────────────────────────
    llm_api_key: str
    llm_base_url: str
    llm_model_id: str
    llm_timeout: int | None

    # ── LLM retry ────────────────────────────────────
    llm_max_retries: int
    llm_retry_base_delay_ms: int
    llm_retry_max_delay_ms: int

    # ── LLM metrics ──────────────────────────────────
    llm_metrics_db_path: str

    # ── LLM cost pricing defaults ────────────────────
    llm_input_cost_yuan_per_1m_tokens: float
    llm_output_cost_yuan_per_1m_tokens: float
    llm_reasoning_cost_yuan_per_1m_tokens: float

    # ── Side LLM (memory) ────────────────────────────
    side_llm_api_key: str
    side_llm_base_url: str
    side_llm_model_id: str

    # ── SubAgent LLM ─────────────────────────────────
    subagent_llm_api_key: str
    subagent_llm_base_url: str
    subagent_llm_model_id: str
    subagent_llm_timeout: int | None

    # ── Memory ───────────────────────────────────────
    memory_enabled: bool
    memory_top_k: int
    memory_recall_top_k: int
    memory_llm_timeout: float

    # ── Tools ────────────────────────────────────────
    browser_headless: bool
    serpapi_key: str


@lru_cache
def get_settings() -> Settings:
    return Settings(
        # ── App ────────────────────────────────
        app_title="Byte E2E Agent Backend",
        agent_workspace=validate_agent_workspace(
            coerce_agent_workspace(os.environ.get("AGENT_WORKSPACE") or _default_agent_workspace())
        ),
        cors_allow_origins=("http://localhost:5173",),
        cors_allow_origin_regex=r"http://localhost:\d+",
        cors_allow_credentials=True,
        # ── LLM ────────────────────────────────
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        llm_base_url=os.environ.get("LLM_BASE_URL", ""),
        llm_model_id=os.environ.get("LLM_MODEL_ID", "gpt-4o"),
        llm_timeout=_env_int_opt("LLM_TIMEOUT"),
        # ── LLM retry ──────────────────────────
        llm_max_retries=_env_int("LLM_MAX_RETRIES", default=3),
        llm_retry_base_delay_ms=_env_int("LLM_RETRY_BASE_DELAY_MS", default=800),
        llm_retry_max_delay_ms=_env_int("LLM_RETRY_MAX_DELAY_MS", default=8000),
        # ── LLM metrics ────────────────────────
        llm_metrics_db_path=(os.environ.get("LLM_METRICS_DB_PATH") or DEFAULT_LLM_METRICS_DB_PATH),
        # ── LLM cost pricing defaults ──────────
        llm_input_cost_yuan_per_1m_tokens=_env_float(
            "LLM_INPUT_COST_YUAN_PER_1M_TOKENS", default=3.0
        ),
        llm_output_cost_yuan_per_1m_tokens=_env_float(
            "LLM_OUTPUT_COST_YUAN_PER_1M_TOKENS", default=6.0
        ),
        llm_reasoning_cost_yuan_per_1m_tokens=_env_float(
            "LLM_REASONING_COST_YUAN_PER_1M_TOKENS",
            default=_env_float("LLM_OUTPUT_COST_YUAN_PER_1M_TOKENS", default=6.0),
        ),
        # ── Side LLM (memory) ──────────────────
        side_llm_api_key=os.environ.get("SIDE_LLM_API_KEY", ""),
        side_llm_base_url=os.environ.get("SIDE_LLM_BASE_URL", ""),
        side_llm_model_id=os.environ.get("SIDE_LLM_MODEL_ID", ""),
        # ── SubAgent LLM ──────────────────────
        subagent_llm_api_key=os.environ.get("SUBAGENT_LLM_API_KEY", ""),
        subagent_llm_base_url=os.environ.get("SUBAGENT_LLM_BASE_URL", ""),
        subagent_llm_model_id=os.environ.get("SUBAGENT_LLM_MODEL_ID", ""),
        subagent_llm_timeout=_env_int_opt("SUBAGENT_LLM_TIMEOUT"),
        # ── Memory ─────────────────────────────
        memory_enabled=_env_bool("MEMORY_ENABLED", default=True),
        memory_top_k=_env_int("MEMORY_TOP_K", default=5),
        memory_recall_top_k=_env_int("MEMORY_RECALL_TOP_K", default=30),
        memory_llm_timeout=_env_float("MEMORY_LLM_TIMEOUT", default=10.0),
        # ── Tools ──────────────────────────────
        browser_headless=_env_bool("BROWSER_HEADLESS", default=True),
        serpapi_key=os.environ.get("SERPAPI_KEY", ""),
    )


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


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


def _env_int_opt(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _env_float(name: str, *, default: float) -> float:
    try:
        return float(os.environ.get(name, ""))
    except ValueError:
        return default
