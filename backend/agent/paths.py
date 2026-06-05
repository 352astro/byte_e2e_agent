"""Agent storage paths — all under PROJECT_ROOT/.agent/workspaces/{uuid}/."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import AGENT_DATA_DIR, PROJECT_ROOT

_SESSION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def valid_session_id(session_id: str) -> bool:
    return bool(_SESSION_ID_RE.fullmatch(session_id))


# ── workspace data root ──────────────────────────────────


def workspace_data_dir(workspace_uuid: str) -> Path:
    """Return PROJECT_ROOT/.agent/workspaces/{uuid}/."""
    return Path(PROJECT_ROOT) / AGENT_DATA_DIR / "workspaces" / workspace_uuid


# ── session paths ────────────────────────────────────────


def session_dir(workspace_uuid: str, session_id: str) -> Path:
    if not valid_session_id(session_id):
        raise ValueError(f"Invalid session_id: {session_id!r}")
    return workspace_data_dir(workspace_uuid) / "sessions" / session_id


def messages_path(workspace_uuid: str, session_id: str) -> Path:
    return session_dir(workspace_uuid, session_id) / "messages.jsonl"


# ── shadow repo ──────────────────────────────────────────


def shadow_repo_dir(workspace_uuid: str) -> Path:
    return workspace_data_dir(workspace_uuid) / ".shadow-vcs"


# ── queries ──────────────────────────────────────────────


def session_exists(workspace_uuid: str, session_id: str) -> bool:
    return messages_path(workspace_uuid, session_id).is_file()


def list_sessions(workspace_uuid: str) -> list[dict[str, str]]:
    """Scan agent storage and return session ids sorted by last activity (newest first)."""
    sessions_root = workspace_data_dir(workspace_uuid) / "sessions"
    if not sessions_root.is_dir():
        return []
    result: list[tuple[float, dict[str, str]]] = []
    for entry in sessions_root.iterdir():
        if not entry.is_dir() or not valid_session_id(entry.name):
            continue
        msg_file = entry / "messages.jsonl"
        if not msg_file.is_file():
            continue
        result.append((msg_file.stat().st_mtime, {"session_id": entry.name}))
    result.sort(key=lambda item: item[0], reverse=True)
    return [info for _, info in result]


# ── init / ensure ────────────────────────────────────────


def init_session_storage(workspace_uuid: str, session_id: str) -> Path:
    """Create empty session directory and messages.jsonl; return messages path."""
    path = messages_path(workspace_uuid, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def ensure_agent_storage(workspace_uuid: str) -> None:
    """Ensure the workspace data directory exists and is writable."""
    root = workspace_data_dir(workspace_uuid)
    root.mkdir(parents=True, exist_ok=True)
    probe = root / ".write_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise ValueError(f"Agent storage not writable: {root} ({exc})") from exc
