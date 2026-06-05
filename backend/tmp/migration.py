"""
One-time migration: {workspace}/.byte_agent/ -> PROJECT_ROOT/.byte_agent/workspaces/{uuid}/

This MUST be done in TWO steps:
  1. {workspace}/.byte_agent/  ->  .agent/workspaces/{uuid}/   (intermediate name)
  2. .agent/                    ->  .byte_agent/                (final rename)

Step 1 uses ".agent" as an intermediate directory to avoid the circular mv that
would occur if AGENT_DATA_DIR == ".byte_agent" and a workspace IS the project root.

Usage:
    cd backend
    python migration.py              # execute both steps
    python migration.py --dry-run    # preview only

After migration is complete and the system is stable, this file can be deleted.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import uuid as _uuid
from pathlib import Path

from app.core.config import AGENT_DATA_DIR

# ── constants ────────────────────────────────────────────

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

# Intermediate name: must NOT equal AGENT_DATA_DIR to avoid circular mv
_MIGRATION_TMP_NAME = ".agent"

OLD_DIR_NAME = ".byte_agent"  # legacy per-workspace directory

# Target paths during step 1 (intermediate)
_TMP_AGENT_DIR = PROJECT_ROOT / _MIGRATION_TMP_NAME
_TMP_WORKSPACES_DIR = _TMP_AGENT_DIR / "workspaces"
_TMP_REGISTRY_FILE = _TMP_AGENT_DIR / "workspaces.json"

# Final paths after step 2
FINAL_AGENT_DIR = PROJECT_ROOT / AGENT_DATA_DIR


# ═══════════════════════════════════════════════════════════
# public API
# ═══════════════════════════════════════════════════════════


def migrate(dry_run: bool = False) -> None:
    step1_move_workspaces(dry_run)
    step2_rename_agent_dir(dry_run)


def step1_move_workspaces(dry_run: bool = False) -> None:
    """Move {workspace}/.byte_agent/ -> .agent/workspaces/{uuid}/."""
    old_workspaces = _read_old_registry()
    new_mapping: dict[str, str] = {}

    _TMP_WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)
    _TMP_AGENT_DIR.mkdir(parents=True, exist_ok=True)

    for ws_path in old_workspaces:
        old_dir = Path(ws_path) / OLD_DIR_NAME
        if not old_dir.is_dir():
            print(f"[SKIP] {old_dir} does not exist")
            continue

        ws_uuid = _uuid.uuid4().hex[:12]
        new_dir = _TMP_WORKSPACES_DIR / ws_uuid

        if new_dir.exists():
            print(f"[WARN] {new_dir} already exists, skipping")
            continue

        print(f"[MOVE] {old_dir} -> {new_dir}")
        if not dry_run:
            shutil.move(str(old_dir), str(new_dir))

        new_mapping[ws_uuid] = ws_path

    if not new_mapping:
        print("Step 1: No .byte_agent/ directories found. Nothing to move.")
        return

    # Merge with any existing entries under the intermediate registry
    existing = _read_registry(_TMP_REGISTRY_FILE)
    existing.update(new_mapping)

    payload = {"workspaces": existing}
    print(f"[WRITE] {_TMP_REGISTRY_FILE}")
    if not dry_run:
        _TMP_REGISTRY_FILE.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    print(
        f"Step 1 done: {len(new_mapping)} workspace(s) moved to .agent/workspaces/.\n"
    )


def step2_rename_agent_dir(dry_run: bool = False) -> None:
    """Rename .agent/ -> .byte_agent/ (final name)."""
    if not _TMP_AGENT_DIR.is_dir():
        print("Step 2: .agent/ does not exist. Nothing to rename.")
        return

    if FINAL_AGENT_DIR.exists():
        print(
            f"Step 2: {FINAL_AGENT_DIR} already exists. "
            "If both .agent/ and .byte_agent/ have data, merge them manually."
        )
        return

    print(f"[RENAME] {_TMP_AGENT_DIR} -> {FINAL_AGENT_DIR}")
    if not dry_run:
        shutil.move(str(_TMP_AGENT_DIR), str(FINAL_AGENT_DIR))

    print("Step 2 done: .agent/ renamed to .byte_agent/.\n")


# ═══════════════════════════════════════════════════════════
# internal
# ═══════════════════════════════════════════════════════════


def _read_old_registry() -> list[str]:
    """Read registry from intermediate or final location, return workspace paths."""
    for path in (_TMP_REGISTRY_FILE, FINAL_AGENT_DIR / "workspaces.json"):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        workspaces = data.get("workspaces")
        if isinstance(workspaces, list):
            return [str(w) for w in workspaces if isinstance(w, str)]
        if isinstance(workspaces, dict):
            return list(workspaces.values())
    return []


def _read_registry(registry_path: Path) -> dict[str, str]:
    """Read a registry file in {uuid: path} format."""
    if not registry_path.is_file():
        return {}
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    workspaces = data.get("workspaces")
    if isinstance(workspaces, dict):
        return {str(k): str(v) for k, v in workspaces.items()}
    return {}


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    migrate(dry_run=dry)
