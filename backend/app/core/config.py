import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env")
load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_title: str
    agent_workspace: str
    cors_allow_origins: tuple[str, ...]
    cors_allow_origin_regex: str
    cors_allow_credentials: bool


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_title="Byte E2E Agent Backend",
        agent_workspace=os.environ.get("AGENT_WORKSPACE", str(PROJECT_ROOT)),
        cors_allow_origins=("http://localhost:5173",),
        cors_allow_origin_regex=r"http://localhost:\d+",
        cors_allow_credentials=True,
    )
