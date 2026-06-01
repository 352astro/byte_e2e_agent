"""Workspace memory management service."""

from __future__ import annotations

import time

from agent.memory.store import MEMORY_KINDS, MemoryRecord
from app.services.context import WorkspaceContext


class MemoryService:
    def __init__(self, ctx: WorkspaceContext) -> None:
        self._ctx = ctx

    async def list_memories(self) -> dict:
        records = await self._ctx.memory_store.list(
            workspace=self._ctx.workspace,
            scopes=("workspace",),
            limit=500,
        )
        return {
            "workspace": self._ctx.workspace,
            "memories": [_memory_to_dict(record) for record in records],
        }

    async def add_memory(self, content: str, kind: str = "fact") -> dict:
        normalized_kind = kind.strip().lower()
        if normalized_kind not in MEMORY_KINDS:
            normalized_kind = "fact"
        now = time.time()
        record = MemoryRecord(
            workspace=self._ctx.workspace,
            session_id="__manual__",
            turn_id="__manual__",
            scope="workspace",
            kind=normalized_kind,
            content=content.strip(),
            confidence=1.0,
            created_at=now,
            updated_at=now,
        )
        await self._ctx.memory_store.add(record)
        records = await self._ctx.memory_store.list(
            workspace=self._ctx.workspace,
            scopes=("workspace",),
            kinds=(normalized_kind,),
            limit=1,
        )
        stored = records[0] if records else record
        return {"workspace": self._ctx.workspace, "memory": _memory_to_dict(stored)}

    async def delete_memory(self, memory_id: str) -> bool:
        return await self._ctx.memory_store.delete(
            memory_id,
            workspace=self._ctx.workspace,
        )


def _memory_to_dict(record: MemoryRecord) -> dict:
    return {
        "id": record.id,
        "workspace": record.workspace,
        "session_id": record.session_id,
        "turn_id": record.turn_id,
        "scope": record.scope,
        "kind": record.kind,
        "content": record.content,
        "confidence": record.confidence,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "last_used_at": record.last_used_at,
        "use_count": record.use_count,
    }
