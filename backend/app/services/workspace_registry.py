"""Persist workspace paths and their UUIDs under PROJECT_ROOT/.agent/workspaces.json.

Format:
    {"workspaces": {"<uuid>": "/absolute/path/to/workspace", ...}}
"""

from __future__ import annotations

import json
import threading
import uuid as _uuid
from pathlib import Path

from app.core.config import AGENT_DATA_DIR, PROJECT_ROOT, resolve_agent_workspace

_REGISTRY_DIR = PROJECT_ROOT / AGENT_DATA_DIR
_REGISTRY_FILE = _REGISTRY_DIR / "workspaces.json"
_WORKSPACES_STORAGE_DIR = _REGISTRY_DIR / "workspaces"
_LOCK = threading.Lock()


def _read_raw() -> dict[str, str]:
    """Return {uuid: path} mapping from disk. Handles legacy list format."""
    if not _REGISTRY_FILE.is_file():
        return {}
    try:
        data = json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError, OSError:
        return {}
    workspaces = data.get("workspaces")
    if isinstance(workspaces, dict):
        return {
            str(k): str(v)
            for k, v in workspaces.items()
            if isinstance(k, str) and isinstance(v, str)
        }
    if isinstance(workspaces, list):
        # Legacy format: convert to new
        result: dict[str, str] = {}
        for item in workspaces:
            if isinstance(item, str):
                result[_uuid.uuid4().hex[:12]] = item
        return result
    return {}


def _write_raw(mapping: dict[str, str]) -> None:
    _REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"workspaces": mapping}
    _REGISTRY_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _normalize_existing(path: str) -> str | None:
    try:
        resolved = resolve_agent_workspace(path)
    except ValueError, OSError:
        return None
    if not Path(resolved).is_dir():
        return None
    return resolved


def register_workspace(path: str) -> tuple[str, str]:
    """Register a workspace path; return (resolved_path, uuid).

    If the path is already registered, return the existing uuid.
    Otherwise generate a new uuid, persist, and return it.
    """
    resolved = _normalize_existing(path)
    if resolved is None:
        raise ValueError(f"Directory does not exist: {path}")

    with _LOCK:
        mapping = _read_raw()
        # Look up existing uuid for this path
        for existing_uuid, existing_path in mapping.items():
            if existing_path == resolved:
                return resolved, existing_uuid
        # New workspace
        ws_uuid = _uuid.uuid4().hex[:12]
        mapping[ws_uuid] = resolved
        _write_raw(mapping)
    return resolved, ws_uuid


def get_workspace_uuid(path: str) -> str | None:
    """Return the uuid for a registered workspace path, or None."""
    resolved = _normalize_existing(path)
    if resolved is None:
        return None
    with _LOCK:
        mapping = _read_raw()
    for ws_uuid, ws_path in mapping.items():
        if ws_path == resolved:
            return ws_uuid
    return None


def get_workspace_path(uuid: str) -> str | None:
    """Return the workspace path for a uuid, or None if not found / stale."""
    with _LOCK:
        mapping = _read_raw()
    path = mapping.get(uuid)
    if path is None:
        return None
    if _normalize_existing(path) is None:
        # Stale entry - prune lazily
        with _LOCK:
            mapping = _read_raw()
            if mapping.get(uuid) == path:
                del mapping[uuid]
                _write_raw(mapping)
        return None
    return path


def list_workspaces() -> dict[str, str]:
    """Return {uuid: path} for all registered, existing workspaces.

    Prunes stale entries automatically.
    """
    with _LOCK:
        raw = _read_raw()
        valid: dict[str, str] = {}
        changed = False
        for ws_uuid, ws_path in raw.items():
            if _normalize_existing(ws_path) is None:
                changed = True
                continue
            valid[ws_uuid] = ws_path
        if changed:
            _write_raw(valid)
        return valid


def workspaces_storage_dir() -> Path:
    """Return PROJECT_ROOT/.agent/workspaces/ (ensure it exists)."""
    _WORKSPACES_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return _WORKSPACES_STORAGE_DIR
