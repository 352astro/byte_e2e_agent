"""Workspace memory management service."""

from __future__ import annotations

import asyncio
import logging
import time

from agent.memory.store import MEMORY_KINDS, MemoryRecord
from app.services.context import WorkspaceContext

logger = logging.getLogger(__name__)

_FEATURE_PROMPT = """\
Create a short recall feature for this manually added memory.

The feature is an internal semantic index used to decide whether this memory
is relevant to a future user question.

Rules:
- Keep it under 16 words.
- Preserve important entities, preferences, decisions, and keywords.
- Do not add facts not present in the memory.
- Return the feature text only.

Kind: {kind}
Memory: {content}
Feature:"""


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
        trimmed = content.strip()
        feature = await _generate_feature(trimmed, normalized_kind)
        now = time.time()
        record = MemoryRecord(
            workspace=self._ctx.workspace,
            session_id="__manual__",
            turn_id="__manual__",
            scope="workspace",
            kind=normalized_kind,
            content=trimmed,
            feature=feature or trimmed,
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
        "feature": record.feature,
        "confidence": record.confidence,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "last_used_at": record.last_used_at,
        "use_count": record.use_count,
    }


async def _generate_feature(content: str, kind: str) -> str:
    if not content:
        return ""
    try:
        from agent.memory._side_client import create_side_client, get_side_model_id

        client = create_side_client()
        model = get_side_model_id()
        prompt = _FEATURE_PROMPT.format(kind=kind, content=content[:2000])

        def _sync_call() -> str:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=48,
                temperature=0.0,
            )
            return resp.choices[0].message.content or ""

        raw = await asyncio.wait_for(asyncio.to_thread(_sync_call), timeout=8.0)
    except Exception as exc:
        logger.warning("MemoryService: feature generation failed: %s", exc)
        return content
    feature = _clean_feature(raw)
    return feature or content


def _clean_feature(text: str) -> str:
    feature = text.strip()
    if feature.startswith("```"):
        feature = feature.strip("`").strip()
    feature = feature.strip("\"' \n\t")
    return " ".join(feature.split())[:200]
