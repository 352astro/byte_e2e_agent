from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LLMCallContext:
    session_id: str | None = None
    message_id: str | None = None
    call_type: str = "agent"


class SQLiteLLMMetricsStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._lock:
            self._init_db()

    def record_call(
        self,
        *,
        model: str,
        created_at: str,
        latency_ms: int,
        context: LLMCallContext | None = None,
        finish_reason: str | None = None,
        usage: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        context = context or LLMCallContext()
        prompt_tokens = _int(usage.get("prompt_tokens")) if usage else None
        completion_tokens = _int(usage.get("completion_tokens")) if usage else None
        total_tokens = _int(usage.get("total_tokens")) if usage else None
        cost_yuan = self._cost_yuan(prompt_tokens, completion_tokens)

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO llm_calls (
                    id, created_at, session_id, message_id, call_type, model,
                    status, finish_reason, latency_ms, prompt_tokens,
                    completion_tokens, total_tokens, cost_yuan, error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    created_at,
                    context.session_id,
                    context.message_id,
                    context.call_type,
                    model,
                    "error" if error else "success",
                    finish_reason,
                    latency_ms,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    cost_yuan,
                    error,
                ),
            )

    def list_calls(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        where, params = _where(session_id)
        columns = """
            id, created_at, session_id, message_id, call_type, model, status,
            finish_reason, latency_ms, prompt_tokens, completion_tokens,
            total_tokens, cost_yuan, error
        """
        with self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM llm_calls {where}",
                params,
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT {columns}
                FROM llm_calls
                {where}
                ORDER BY created_at DESC, rowid DESC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "pagination": {"limit": limit, "offset": offset, "total": total},
        }

    def summary(self, session_id: str | None = None) -> dict[str, Any]:
        where, params = _where(session_id)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS total_calls,
                    SUM(status = 'success') AS successful_calls,
                    SUM(status = 'error') AS errored_calls,
                    AVG(latency_ms) AS avg_latency_ms,
                    MIN(latency_ms) AS min_latency_ms,
                    MAX(latency_ms) AS max_latency_ms,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    SUM(cost_yuan) AS cost_yuan
                FROM llm_calls
                {where}
                """,
                params,
            ).fetchone()
        return {
            "total_calls": row["total_calls"] or 0,
            "successful_calls": row["successful_calls"] or 0,
            "errored_calls": row["errored_calls"] or 0,
            "avg_latency_ms": _round(row["avg_latency_ms"]),
            "min_latency_ms": row["min_latency_ms"],
            "max_latency_ms": row["max_latency_ms"],
            "prompt_tokens": row["prompt_tokens"] or 0,
            "completion_tokens": row["completion_tokens"] or 0,
            "total_tokens": row["total_tokens"] or 0,
            "cost_yuan": _round(row["cost_yuan"], 8),
        }

    def dashboard(
        self,
        *,
        limit: int = 20,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "summary": self.summary(session_id=session_id),
            "by_model": self.by_model(session_id=session_id),
            "recent_calls": self.list_calls(
                limit=limit,
                session_id=session_id,
            )["items"],
        }

    def by_model(self, session_id: str | None = None) -> list[dict[str, Any]]:
        where, params = _where(session_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    model,
                    COUNT(*) AS total_calls,
                    SUM(status = 'error') AS errored_calls,
                    AVG(latency_ms) AS avg_latency_ms,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    SUM(cost_yuan) AS cost_yuan
                FROM llm_calls
                {where}
                GROUP BY model
                ORDER BY total_calls DESC, model ASC
                """,
                params,
            ).fetchall()
        return [
            {
                "model": row["model"],
                "total_calls": row["total_calls"],
                "errored_calls": row["errored_calls"] or 0,
                "avg_latency_ms": _round(row["avg_latency_ms"]),
                "total_tokens": row["total_tokens"] or 0,
                "cost_yuan": _round(row["cost_yuan"], 8),
            }
            for row in rows
        ]

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS llm_calls (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    session_id TEXT,
                    message_id TEXT,
                    call_type TEXT NOT NULL,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    finish_reason TEXT,
                    latency_ms INTEGER NOT NULL,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    total_tokens INTEGER,
                    cost_yuan REAL,
                    error TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_llm_calls_created_at
                    ON llm_calls(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_llm_calls_session_id
                    ON llm_calls(session_id);
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(llm_calls)").fetchall()
            }
            if "cost_yuan" not in columns:
                conn.execute("ALTER TABLE llm_calls ADD COLUMN cost_yuan REAL")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _cost_yuan(
        self,
        prompt_tokens: int | None,
        completion_tokens: int | None,
    ) -> float:
        input_price = _env_float("LLM_INPUT_COST_YUAN_PER_1M_TOKENS", 3.0)
        output_price = _env_float("LLM_OUTPUT_COST_YUAN_PER_1M_TOKENS", 6.0)
        return (
            ((prompt_tokens or 0) * input_price)
            + ((completion_tokens or 0) * output_price)
        ) / 1_000_000


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def usage_to_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return None


def _where(session_id: str | None) -> tuple[str, tuple[Any, ...]]:
    if not session_id:
        return "", ()
    return "WHERE session_id = ?", (session_id,)


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _round(value: Any, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)
