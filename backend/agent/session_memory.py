"""SessionMemory — per-session JSON metadata + async JSONL event log."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.turn import ToolStep, Turn

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _turn_from_dict(data: dict) -> Turn:
    return Turn(
        role=data["role"],
        question=data.get("question", ""),
        reasoning=data.get("reasoning", ""),
        content=data.get("content", ""),
        tool_calls=[
            ToolStep(
                name=tc["name"],
                arguments=tc.get("arguments", {}),
                result=tc.get("result"),
            )
            for tc in data.get("tool_calls", [])
        ],
        finish_answer=data.get("finish_answer"),
    )


class SessionMemory:
    """Persist one session under workspace/.tmp/{session_id}/."""

    def __init__(self, workspace: str | Path, session_id: str) -> None:
        if not _SESSION_ID_RE.fullmatch(session_id):
            raise ValueError(f"Invalid session_id: {session_id!r}")
        self.workspace = Path(workspace)
        self.session_id = session_id
        self.session_dir = self.workspace / ".tmp" / session_id
        self.meta_path = self.session_dir / f"{session_id}.json"
        self.events_path = self.session_dir / "messages.jsonl"
        self._lock = asyncio.Lock()

    def ensure(self, session_name: str = "") -> None:
        """Create the session directory and metadata file if missing."""
        self.session_dir.mkdir(parents=True, exist_ok=True)
        if self.meta_path.exists():
            return
        now = _now_iso()
        self._write_meta(
            {
                "session_id": self.session_id,
                "session_name": session_name,
                "created_at": now,
                "updated_at": now,
            }
        )

    def load(self) -> tuple[dict[str, Any], list[dict], list[Turn]]:
        """Load metadata, OpenAI messages, and frontend turns from disk."""
        self.ensure()
        meta = self._read_meta()
        messages: list[dict] = []
        turns: list[Turn] = []

        if not self.events_path.exists():
            return meta, messages, turns

        with open(self.events_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                kind = record.get("kind")
                data = record.get("data")
                if kind == "message" and isinstance(data, dict):
                    messages.append(data)
                elif kind == "turn" and isinstance(data, dict):
                    try:
                        turns.append(_turn_from_dict(data))
                    except (KeyError, TypeError):
                        continue

        return meta, messages, turns

    async def append_message(self, message: dict) -> None:
        await self._append_record({"kind": "message", "data": message})

    async def append_turn(self, turn: Turn) -> None:
        await self._append_record({"kind": "turn", "data": asdict(turn)})

    async def touch(self, session_name: str | None = None) -> None:
        """Update metadata asynchronously."""
        async with self._lock:
            await asyncio.to_thread(self._touch_sync, session_name)

    async def ensure_session_name(self, first_question: str) -> None:
        """Use the first user input as session_name when it is still empty."""
        name = first_question.strip()
        if len(name) > 80:
            name = name[:77] + "..."
        async with self._lock:
            await asyncio.to_thread(self._ensure_session_name_sync, name)

    async def _append_record(self, record: dict) -> None:
        record["created_at"] = _now_iso()
        async with self._lock:
            await asyncio.to_thread(self._append_record_sync, record)

    def _append_record_sync(self, record: dict) -> None:
        self.ensure()
        with open(self.events_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")
        self._touch_sync()

    def _read_meta(self) -> dict[str, Any]:
        try:
            with open(self.meta_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            now = _now_iso()
            return {
                "session_id": self.session_id,
                "session_name": "",
                "created_at": now,
                "updated_at": now,
            }

    def _write_meta(self, meta: dict[str, Any]) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.meta_path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
        tmp_path.replace(self.meta_path)

    def _touch_sync(self, session_name: str | None = None) -> None:
        self.ensure()
        meta = self._read_meta()
        if session_name is not None:
            meta["session_name"] = session_name
        meta["updated_at"] = _now_iso()
        self._write_meta(meta)

    def _ensure_session_name_sync(self, name: str) -> None:
        self.ensure()
        meta = self._read_meta()
        if not meta.get("session_name"):
            meta["session_name"] = name
            meta["updated_at"] = _now_iso()
            self._write_meta(meta)
