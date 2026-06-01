from __future__ import annotations

import json

import pytest

from agent.memory.memory_hook import MemoryHook
from agent.memory.store import InMemoryMemoryStore, MemoryRecord, SQLiteMemoryStore
from shared.types import Message


@pytest.mark.asyncio
async def test_sqlite_memory_store_dedupes_by_workspace_scope_kind_hash(tmp_path):
    store = SQLiteMemoryStore(tmp_path)

    await store.add(
        MemoryRecord(
            workspace=str(tmp_path),
            session_id="s1",
            turn_id="t1",
            scope="workspace",
            kind="decision",
            content="Use SQLite FTS for memory recall.",
        )
    )
    await store.add(
        MemoryRecord(
            workspace=str(tmp_path),
            session_id="s2",
            turn_id="t2",
            scope="workspace",
            kind="decision",
            content="Use SQLite FTS for memory recall.",
        )
    )

    assert await store.count() == 1
    results = await store.search(
        "SQLite memory",
        workspace=str(tmp_path),
        scopes=("workspace",),
    )
    assert len(results) == 1
    assert results[0].session_id == "s2"
    assert results[0].use_count >= 1


@pytest.mark.asyncio
async def test_memory_store_filters_session_scope(tmp_path):
    store = SQLiteMemoryStore(tmp_path)
    await store.add(
        MemoryRecord(
            workspace=str(tmp_path),
            session_id="s1",
            scope="session",
            kind="fact",
            content="Session alpha uses pytest.",
        )
    )
    await store.add(
        MemoryRecord(
            workspace=str(tmp_path),
            session_id="s2",
            scope="session",
            kind="fact",
            content="Session beta uses pytest.",
        )
    )

    results = await store.search(
        "pytest",
        session_id="s1",
        workspace=str(tmp_path),
        scopes=("session",),
    )

    assert [record.session_id for record in results] == ["s1"]


@pytest.mark.asyncio
async def test_memory_store_recalls_cjk_natural_question(tmp_path):
    store = SQLiteMemoryStore(tmp_path)
    await store.add(
        MemoryRecord(
            workspace=str(tmp_path),
            session_id="s1",
            scope="workspace",
            kind="preference",
            content="用户最爱喝芒果味奶昔。",
        )
    )

    results = await store.search(
        "请问我最爱喝什么？",
        session_id="s2",
        workspace=str(tmp_path),
        scopes=("workspace", "session"),
    )

    assert len(results) == 1
    assert results[0].content == "用户最爱喝芒果味奶昔。"


class ExtractingMemoryHook(MemoryHook):
    async def _llm_call(self, prompt: str, max_tokens: int = 120) -> str:
        return json.dumps(
            {
                "memories": [
                    {
                        "scope": "session",
                        "kind": "preference",
                        "content": "User prefers concise engineering answers.",
                        "feature": "answer style preference: concise engineering answers",
                        "confidence": 0.9,
                    },
                    {
                        "scope": "workspace",
                        "kind": "fact",
                        "content": "API key sk-secret must never be stored.",
                        "feature": "sensitive credential that must be skipped",
                        "confidence": 0.99,
                    },
                ]
            }
        )


@pytest.mark.asyncio
async def test_memory_hook_extracts_structured_memory_and_skips_secrets():
    store = InMemoryMemoryStore()
    hook = ExtractingMemoryHook(store, workspace="/repo")

    msg = Message.user_message("m1", "turn1", "I prefer concise answers.")
    await hook.on_message_finish(msg=msg, session_id="s1")
    await hook.on_turn_end(turn_id="turn1", session_id="s1")
    await hook.flush()

    results = await store.search("concise", workspace="/repo")
    assert len(results) == 1
    assert results[0].kind == "preference"
    assert results[0].scope == "workspace"
    assert "concise" in results[0].content
    assert "concise engineering" in results[0].feature


class PickingMemoryHook(MemoryHook):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pick_prompt = ""

    async def _llm_call(self, prompt: str, max_tokens: int = 120) -> str:
        self.pick_prompt = prompt
        return "1"


@pytest.mark.asyncio
async def test_memory_hook_recalls_by_llm_feature_pick_without_keyword_search():
    store = InMemoryMemoryStore()
    await store.add(
        MemoryRecord(
            workspace="/repo",
            session_id="s1",
            scope="workspace",
            kind="preference",
            content="用户最爱喝芒果味奶昔。",
            feature="饮品偏好：最爱芒果味奶昔",
        )
    )
    hook = PickingMemoryHook(store, workspace="/repo", top_k=1, recall_top_k=20)

    injected = await hook.on_context_assemble(
        turn_id="t2",
        session_id="s2",
        user_question="我平时喜欢什么饮品？",
    )

    assert "饮品偏好" in hook.pick_prompt
    assert "用户最爱喝芒果味奶昔。" in injected[0]["content"]
