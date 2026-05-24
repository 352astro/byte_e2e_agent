"""Persist Transcripts under workspace/.tmp/{session_id}/messages.jsonl.

JSONL format (one line per transcript):
  {"kind": "user_question", "uuid": "abc123", "message": {"role": "user", "content": "..."}}
  {"kind": "assistant",      "uuid": "def456", "message": {"role": "assistant", ...}}
  {"kind": "tool_result",    "uuid": "ghi789", "message": {"role": "tool", ...}}
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid as _uuid
from pathlib import Path
from typing import Any

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


# ── Public API ────────────────────────────────────────────


def load_session(
    workspace: str | Path,
    session_id: str,
    llm_client: Any,
    toolset: Any = None,
    sandbox: Any = None,
):
    """Rebuild a Session from persisted Transcripts.

    Returns a Session whose _transcripts is populated from the JSONL file.
    The caller is responsible for providing llm_client / toolset / sandbox
    since they are not serialisable.
    """
    # Lazy import to avoid circular dependency at module level
    from agent.session import Session  # noqa: F811
    from agent.transcript import Transcript

    session = Session(
        llm_client=llm_client,
        toolset=toolset,
        sandbox=sandbox,
        session_id=session_id,
    )

    messages_path = _messages_path(workspace, session_id)
    if not messages_path.exists():
        return session

    transcripts: list[Transcript] = []
    with open(messages_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and "uuid" in record and "kind" in record:
                # New Transcript format: {kind, uuid, message}
                transcripts.append(
                    Transcript(
                        id=record["uuid"],
                        kind=record["kind"],
                        message=record.get("message", {}),
                    )
                )
            elif isinstance(record, dict) and "role" in record:
                # Legacy: bare message dict — infer kind from role
                role = record.get("role", "")
                kind = {
                    "user": "user_question",
                    "assistant": "assistant",
                    "tool": "tool_result",
                }.get(role, "assistant")
                transcripts.append(
                    Transcript(
                        id=_uuid.uuid4().hex,
                        kind=kind,
                        message=record,
                    )
                )

    session._transcripts = transcripts
    return session


async def save_transcript(
    workspace: str | Path,
    session_id: str,
    kind: str,
    transcript_uuid: str,
    message: dict,
) -> None:
    """Append one Transcript record to the session JSONL file."""
    await asyncio.to_thread(
        _save_transcript_sync, workspace, session_id, kind, transcript_uuid, message
    )


def _save_transcript_sync(
    workspace: str | Path,
    session_id: str,
    kind: str,
    transcript_uuid: str,
    message: dict,
) -> None:
    messages_path = _messages_path(workspace, session_id)
    messages_path.parent.mkdir(parents=True, exist_ok=True)
    record = {"kind": kind, "uuid": transcript_uuid, "message": message}
    with open(messages_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        fh.write("\n")
