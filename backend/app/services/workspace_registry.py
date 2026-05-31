"""Persist known agent workspace paths under PROJECT_ROOT/.agent/."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from app.core.config import PROJECT_ROOT, resolve_agent_workspace

_REGISTRY_DIR = PROJECT_ROOT / ".agent"
_REGISTRY_FILE = _REGISTRY_DIR / "workspaces.json"
_LOCK = threading.Lock()


def _read_raw() -> list[str]:
    if not _REGISTRY_FILE.is_file():
        return []
    try:
        data = json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    workspaces = data.get("workspaces")
    if not isinstance(workspaces, list):
        return []
    return [str(item) for item in workspaces if isinstance(item, str)]


def _write_raw(paths: list[str]) -> None:
    _REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"workspaces": paths}
    _REGISTRY_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _normalize_existing(path: str) -> str | None:
    try:
        resolved = resolve_agent_workspace(path)
    except (ValueError, OSError):
        return None
    if not Path(resolved).is_dir():
        return None
    return resolved


def register_workspace(path: str) -> str:
    """Add a workspace path to the registry; return resolved absolute path."""
    resolved = _normalize_existing(path)
    if resolved is None:
        raise ValueError(f"Directory does not exist: {path}")

    with _LOCK:
        paths = _read_raw()
        if resolved not in paths:
            paths.append(resolved)
            _write_raw(paths)
    return resolved


def list_workspaces() -> list[str]:
    """Return registered workspace paths that still exist (prunes stale entries)."""
    with _LOCK:
        raw = _read_raw()
        valid: list[str] = []
        seen: set[str] = set()
        for item in raw:
            resolved = _normalize_existing(item)
            if resolved is None or resolved in seen:
                continue
            seen.add(resolved)
            valid.append(resolved)
        if valid != raw:
            _write_raw(valid)
        return valid
