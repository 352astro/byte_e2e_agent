"""Agent storage paths under workspace."""

from __future__ import annotations

import re
from pathlib import Path

TMP_DIR = ".byte_agent"

_SESSION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def valid_session_id(session_id: str) -> bool:
    return bool(_SESSION_ID_RE.fullmatch(session_id))


def agent_tmp_root(workspace: str | Path) -> Path:
    return Path(workspace).expanduser().resolve() / TMP_DIR


def session_dir(workspace: str | Path, session_id: str) -> Path:
    if not valid_session_id(session_id):
        raise ValueError(f"Invalid session_id: {session_id!r}")
    return agent_tmp_root(workspace) / "sessions" / session_id


def messages_path(workspace: str | Path, session_id: str) -> Path:
    return session_dir(workspace, session_id) / "messages.jsonl"


def shadow_repo_dir(workspace: str | Path) -> Path:
    return agent_tmp_root(workspace) / ".shadow-vcs"


def session_exists(workspace: str | Path, session_id: str) -> bool:
    return messages_path(workspace, session_id).is_file()


def list_sessions(workspace: str | Path) -> list[dict[str, str]]:
    """Scan agent storage and return session ids sorted by last activity (newest first)."""
    sessions_root = agent_tmp_root(workspace) / "sessions"
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


def init_session_storage(workspace: str | Path, session_id: str) -> Path:
    """Create empty session directory and messages.jsonl; return messages path."""
    path = messages_path(workspace, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def ensure_agent_storage(workspace: str | Path) -> None:
    """Ensure the agent storage directory exists and is writable."""
    tmp_root = agent_tmp_root(workspace)
    tmp_root.mkdir(parents=True, exist_ok=True)
    probe = tmp_root / ".write_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise ValueError(f"Agent storage not writable: {tmp_root} ({exc})") from exc
