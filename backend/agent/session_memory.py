"""Persist session messages under workspace/.tmp/{session_id}/messages.jsonl."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _workspace_path(workspace: str | Path) -> Path:
    return Path(workspace).expanduser().resolve()


def _session_dir(workspace: str | Path, session_id: str) -> Path:
    _validate_session_id(session_id)
    return _workspace_path(workspace) / ".tmp" / session_id


def _messages_path(workspace: str | Path, session_id: str) -> Path:
    return _session_dir(workspace, session_id) / "messages.jsonl"


def _validate_session_id(session_id: str) -> None:
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError(f"Invalid session_id: {session_id!r}")


def load_memory(workspace: str | Path, session_id: str) -> list[dict]:
    """Load OpenAI-format messages from the session JSONL file."""
    messages_path = _messages_path(workspace, session_id)
    if not messages_path.exists():
        return []

    messages: list[dict] = []
    with open(messages_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("kind") == "message" and isinstance(record.get("data"), dict):
                messages.append(record["data"])
            else:
                messages.append(record)
    return messages


async def save_memory(workspace: str | Path, session_id: str, message: dict) -> None:
    """Append one OpenAI-format message to the session JSONL file."""
    await asyncio.to_thread(_save_memory_sync, workspace, session_id, message)


def _save_memory_sync(workspace: str | Path, session_id: str, message: dict) -> None:
    messages_path = _messages_path(workspace, session_id)
    messages_path.parent.mkdir(parents=True, exist_ok=True)
    with open(messages_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")))
        fh.write("\n")
