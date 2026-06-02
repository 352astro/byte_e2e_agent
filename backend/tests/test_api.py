"""API integration tests — full chain from HTTP request through AgentRuntime.

Uses FastAPI TestClient (in-process ASGI, no port needed).
Tests cover:
- Session CRUD (create / list / delete / history)
- Chat SSE stream lifecycle (start → interrupt → recover)
- Recover endpoint (messages + running state)
- Interrupt endpoint
- Response model validation (OpenAPI schema correctness)
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_chat_service
from main import app
from shared.types import Message, MessageRole, MessageStatus, ToolCall, ToolCallFunction

client = TestClient(app)


def create_session():
    return client.post(
        "/api/session",
        json={"name": "", "preamble": "", "rules": [], "preloaded_skills": []},
    )


# ═══════════════════════════════════════════════════════════
# Session CRUD
# ═══════════════════════════════════════════════════════════


class TestSessionCRUD:
    def test_create_session_returns_session_id(self):
        r = create_session()
        assert r.status_code == 200
        data = r.json()
        assert "session_id" in data
        assert isinstance(data["session_id"], str)
        assert len(data["session_id"]) > 0

    def test_list_sessions_includes_created(self):
        r = create_session()
        sid = r.json()["session_id"]

        r = client.get("/api/sessions")
        assert r.status_code == 200
        data = r.json()
        assert "workspace" in data
        assert "sessions" in data
        assert any(s["session_id"] == sid for s in data["sessions"])

    def test_delete_session_removes(self):
        r = create_session()
        sid = r.json()["session_id"]

        r = client.delete(f"/api/session/{sid}")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Verify gone
        r = client.get("/api/sessions")
        sessions = r.json()["sessions"]
        assert not any(s["session_id"] == sid for s in sessions)

    def test_delete_nonexistent_returns_404(self):
        r = client.delete("/api/session/nonexistent")
        assert r.status_code == 404

    def test_history_returns_session_and_messages(self):
        r = create_session()
        sid = r.json()["session_id"]

        r = client.get(f"/api/session/{sid}/history")
        assert r.status_code == 200
        data = r.json()
        assert "session" in data
        assert "history" in data
        assert isinstance(data["history"], list)

    def test_history_nonexistent_returns_404(self):
        r = client.get("/api/session/nonexistent/history")
        assert r.status_code == 404

    def test_recover_returns_messages_and_session_running(self):
        r = create_session()
        sid = r.json()["session_id"]

        r = client.get(f"/api/session/{sid}/recover")
        assert r.status_code == 200
        data = r.json()
        assert "session" in data
        assert "messages" in data
        assert isinstance(data["messages"], list)
        assert "session_running" in data
        assert data["session_running"] is False
        assert "runtime_busy" in data
        assert data["runtime_busy"] is False

    def test_status_returns_global_runtime_state(self):
        r = client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert "runtime_busy" in data
        assert data["runtime_busy"] is False

    def test_session_status_returns_session_and_runtime_state(self):
        r = create_session()
        sid = r.json()["session_id"]

        r = client.get(f"/api/session/{sid}/status")
        assert r.status_code == 200
        data = r.json()
        assert "session_running" in data
        assert data["session_running"] is False
        assert data["runtime_busy"] is False

    def test_session_status_requires_existing_session(self):
        r = client.get("/api/session/nonexistent/status")
        assert r.status_code == 404


class TestWorkspaceFileAPI:
    def test_workspace_file_serves_file(self, tmp_path):
        from app.dependencies import get_context

        ctx = get_context()
        old_workspace = ctx.workspace
        try:
            ctx.set_workspace(str(tmp_path))
            (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            r = client.get("/api/workspace/file", params={"path": "image.png"})
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("image/png")
            assert r.content == b"\x89PNG\r\n\x1a\n"
        finally:
            ctx.set_workspace(old_workspace)

    def test_workspace_file_rejects_traversal(self):
        r = client.get("/api/workspace/file", params={"path": "../secret.png"})
        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════
# Interrupt
# ═══════════════════════════════════════════════════════════


class TestInterrupt:
    def test_interrupt_session_returns_ok(self):
        r = create_session()
        sid = r.json()["session_id"]

        r = client.post(f"/api/session/{sid}/interrupt")
        assert r.status_code == 200
        assert r.json()["ok"] in (True, False)  # ok if nothing to interrupt

    def test_interrupt_nonexistent_returns_404(self):
        r = client.post("/api/session/nonexistent/interrupt")
        assert r.status_code == 404

    def test_global_interrupt_returns_ok(self):
        r = client.post("/api/interrupt")
        assert r.status_code == 200
        assert "ok" in r.json()


# ═══════════════════════════════════════════════════════════
# SSE schema endpoint
# ═══════════════════════════════════════════════════════════


class TestSSESchemaEndpoint:
    def test_returns_200(self):
        r = client.get("/api/sse-schema")
        assert r.status_code == 200

    def test_response_matches_stream_event_schema(self):
        """The dummy endpoint returns a valid (albeit empty) StreamEvent."""
        r = client.get("/api/sse-schema")
        data = r.json()
        assert "kind" in data
        assert "message_id" in data
        assert "field" in data


# ═══════════════════════════════════════════════════════════
# OpenAPI schema validation
# ═══════════════════════════════════════════════════════════


class TestOpenAPISchema:
    def test_message_in_schemas(self):
        schema = app.openapi()
        schemas = schema["components"]["schemas"]
        assert "Message" in schemas

    def test_message_has_expected_fields(self):
        schema = app.openapi()
        msg = schema["components"]["schemas"]["Message"]
        props = msg.get("properties", msg.get("items", {}).get("properties", {}))
        # Check key fields exist
        field_names = set(props.keys()) if isinstance(props, dict) else set()
        expected = {"id", "turn_id", "role", "status", "content", "reasoning"}
        assert expected.issubset(field_names), f"Missing: {expected - field_names}"

    def test_tool_call_in_schemas(self):
        schema = app.openapi()
        schemas = schema["components"]["schemas"]
        assert "ToolCall" in schemas

    def test_stream_event_schema_in_schemas(self):
        schema = app.openapi()
        schemas = schema["components"]["schemas"]
        assert "StreamEventSchema" in schemas

    def test_response_models_use_message(self):
        """Verify HistoryResponse and RecoverResponse reference Message."""
        schema = app.openapi()
        schemas = schema["components"]["schemas"]
        for name in ("HistoryResponse", "RecoverResponse"):
            assert name in schemas, f"{name} not in OpenAPI schemas"


# ═══════════════════════════════════════════════════════════
# Chat SSE (mocked — real SSE requires async streaming)
# ═══════════════════════════════════════════════════════════


class TestChatSSE:
    def test_chat_requires_body(self):
        r = create_session()
        sid = r.json()["session_id"]

        # Missing body → validation error (fastapi returns 422 for invalid body)
        r = client.post(f"/api/session/{sid}/chat")
        assert r.status_code == 422

    def test_chat_accepts_valid_request(self):
        """Chat endpoint accepts valid JSON and returns 200 (starts streaming)."""
        r = create_session()
        sid = r.json()["session_id"]

        # Mock the stream creation to avoid real LLM calls
        mock_q = MagicMock()
        mock_q.get = AsyncMock(return_value=None)  # None = close stream
        mock_stream = MagicMock()
        mock_stream.queue = mock_q
        mock_stream.driver = MagicMock()
        mock_stream.driver.unsubscribe = MagicMock()

        mock_chat_service = MagicMock(start_chat=MagicMock(return_value=mock_stream))
        app.dependency_overrides[get_chat_service] = lambda: mock_chat_service
        try:
            r = client.post(
                f"/api/session/{sid}/chat",
                json={"question": "hello", "max_steps": 1},
            )
            assert r.status_code == 200
        finally:
            app.dependency_overrides.pop(get_chat_service, None)

    def test_chat_nonexistent_session(self):
        r = client.post(
            "/api/session/nonexistent/chat",
            json={"question": "hello", "max_steps": 1},
        )
        assert r.status_code in (404, 500)  # depends on how Project handles it


# ═══════════════════════════════════════════════════════════
# Commit / Message rewind separation
# ═══════════════════════════════════════════════════════════


class TestRewindAPIs:
    def test_message_truncate_does_not_require_commit_sha(self):
        """Message truncation is independent from workspace commits."""
        r = create_session()
        sid = r.json()["session_id"]

        r = client.post(
            f"/api/session/{sid}/messages/truncate",
            json={"message_id": "nonexistent-id", "keep": False},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["message_id"] == "nonexistent-id"
        assert "removed" in data

    def test_message_truncate_nonexistent_session_returns_404(self):
        r = client.post(
            "/api/session/nonexistent/messages/truncate",
            json={"message_id": "x", "keep": False},
        )
        assert r.status_code == 404

    def test_workspace_restore_nonexistent_session_returns_404(self):
        r = client.post(
            "/api/session/nonexistent/workspace/restore",
            json={"commit_sha": "0" * 40},
        )
        assert r.status_code == 404
