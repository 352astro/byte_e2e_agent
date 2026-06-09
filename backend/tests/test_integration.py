"""
Integration test: trace a full session lifecycle with real LLM calls.

Covers the complete chain:
  Chat 1 → SSE stream → collect events
  Chat 2 → SSE stream → collect events
  Refresh (GET /recover) → verify message integrity

Requires LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_ID in environment.
Skip if not configured.
"""

from __future__ import annotations

import contextlib
import json
import os

import pytest
from dotenv import load_dotenv
from httpx import Client

load_dotenv()  # load .env file for LLM_API_KEY etc.

BACKEND = "http://localhost:8000"

# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _env_configured() -> bool:
    return bool(
        os.getenv("LLM_API_KEY") and os.getenv("LLM_BASE_URL") and os.getenv("LLM_MODEL_ID")
    )


def _backend_available() -> bool:
    try:
        with Client(base_url=BACKEND, timeout=1.0) as client:
            return client.get("/api/hello").status_code == 200
    except Exception:
        return False


def _read_sse(client: Client, sid: str, question: str) -> list[dict]:
    """POST /chat, read SSE stream, return all parsed events."""
    events: list[dict] = []
    with client.stream(
        "POST",
        f"/api/session/{sid}/chat",
        json={"question": question, "max_steps": 3},
        timeout=120,
    ) as response:
        assert response.status_code == 200, f"Chat failed: {response.status_code}"
        for line in response.iter_lines():
            if line.startswith("data: "):
                with contextlib.suppress(json.JSONDecodeError):
                    events.append(json.loads(line[6:]))
    return events


def _event_counts(events: list[dict]) -> dict:
    """Count events by kind."""
    counts: dict[str, int] = {}
    for e in events:
        kind = e.get("kind", "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def _messages_by_role(events: list[dict]) -> dict[str, set[str]]:
    """Collect message_ids by role from message_start events."""
    by_role: dict[str, set[str]] = {}
    for e in events:
        if e.get("kind") == "message_start":
            role = e.get("role", "assistant")
            mid = e.get("message_id", "")
            if mid:
                by_role.setdefault(role, set()).add(mid)
    return by_role


# ═══════════════════════════════════════════════════════════
# Tests — require real LLM
# ═══════════════════════════════════════════════════════════


@pytest.mark.integration
@pytest.mark.skipif(not _env_configured(), reason="LLM env vars not set")
@pytest.mark.skipif(not _backend_available(), reason="backend server is not running on localhost:8000")
class TestFullSessionTrace:
    """End-to-end: 2 chats + refresh."""

    def test_session_lifecycle(self):
        client = Client(base_url=BACKEND)

        # ── Create session ──────────────────────────
        r = client.post(
            "/api/session", json={"name": "", "preamble": "", "rules": [], "preloaded_skills": []}
        )
        assert r.status_code == 200
        sid = r.json()["session_id"]
        assert sid
        print(f"\n  Session: {sid}")

        # ═══════════════════════════════════════════
        # Chat 1: simple question
        # ═══════════════════════════════════════════
        events1 = _read_sse(client, sid, "Say 'hello' and nothing else.")
        counts1 = _event_counts(events1)
        by_role1 = _messages_by_role(events1)

        print(f"  Chat 1 events: {len(events1)} total, {counts1}")
        print(f"  Chat 1 roles: {by_role1}")

        # ── Assertions ─────────────────────────────
        assert "message_start" in counts1, "No message_start events"
        assert "message_finish" in counts1, "No message_finish events"

        # Should have at least: user message + assistant message
        assert "user" in by_role1, "No user message_start with role=user"
        assert "assistant" in by_role1, "No assistant message_start"

        # chunk_delta should exist (content streaming)
        assert "chunk_delta" in counts1, "No chunk_delta — streaming not working"

        # ═══════════════════════════════════════════
        # Chat 2: question that may trigger reasoning
        # ═══════════════════════════════════════════
        events2 = _read_sse(
            client,
            sid,
            "Think step by step: what is 15 * 7? Return only the answer.",
        )
        counts2 = _event_counts(events2)
        by_role2 = _messages_by_role(events2)

        print(f"  Chat 2 events: {len(events2)} total, {counts2}")
        print(f"  Chat 2 roles: {by_role2}")

        # ── Assertions ─────────────────────────────
        assert "message_start" in counts2
        assert "message_finish" in counts2
        assert "chunk_delta" in counts2
        assert "user" in by_role2
        assert "assistant" in by_role2

        # ═══════════════════════════════════════════
        # Refresh — verify recover endpoint
        # ═══════════════════════════════════════════
        r = client.get(f"/api/session/{sid}/recover")
        assert r.status_code == 200
        data = r.json()

        assert "messages" in data, f"Recover missing 'messages': {list(data.keys())}"
        messages = data["messages"]
        assert isinstance(messages, list)
        assert len(messages) >= 4, (
            f"Expected >=4 messages (2 user + 2 assistant), got {len(messages)}"
        )

        print(f"  Recover: {len(messages)} messages, running={data.get('running')}")

        # ── Verify message structure ───────────────
        for i, msg in enumerate(messages):
            assert "id" in msg, f"Message {i} missing id"
            assert "role" in msg, f"Message {i} missing role"
            assert "status" in msg, f"Message {i} missing status"
            assert "content" in msg, f"Message {i} missing content"

        roles = [m["role"] for m in messages]
        assert "user" in roles, f"No user messages in recover: {roles}"
        assert "assistant" in roles, f"No assistant messages in recover: {roles}"

        # ── Print message summary ──────────────────
        for i, msg in enumerate(messages):
            has_reasoning = bool(msg.get("reasoning"))
            has_tool_calls = bool(msg.get("tool_calls"))
            print(
                f"    [{i}] {msg['role']:10} status={msg['status']:10} "
                f"content={msg['content'][:50]!r} "
                f"reasoning={'YES' if has_reasoning else 'no'} "
                f"tool_calls={'YES' if has_tool_calls else 'no'}"
            )

        # ═══════════════════════════════════════════
        # Summary
        # ═══════════════════════════════════════════
        print(
            f"\n  ✅ Full trace: {len(events1)}+{len(events2)} SSE events, "
            f"{len(messages)} messages in recover"
        )
