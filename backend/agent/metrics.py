"""Metrics — LLM 调用指标存储（SQLite）。

表:
- llm_calls      每次 LLM 调用的完整记录
- model_pricing  模型定价表（自动发现 + 用户自定义）
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
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

    # ═══════════════════════════════════════════════════════
    # record_call
    # ═══════════════════════════════════════════════════════

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
        workspace_root: str = "",
        reasoning_tokens: int | None = None,
        prompt_cached_tokens: int | None = None,
        prompt_cache_hit: int | None = None,
        prompt_cache_miss: int | None = None,
    ) -> None:
        context = context or LLMCallContext()
        _usage = usage or {}
        prompt_tokens = _int(_usage.get("prompt_tokens"))
        completion_tokens = _int(_usage.get("completion_tokens"))
        total_tokens = _int(_usage.get("total_tokens"))

        # 自动发现模型定价
        self._ensure_pricing(model)

        # 查定价表计算费用
        cost_yuan = self._cost_yuan(
            model, prompt_tokens, completion_tokens, reasoning_tokens, prompt_cached_tokens
        )

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO llm_calls (
                    id, created_at, workspace_root, session_id, message_id,
                    call_type, model, status, finish_reason, latency_ms,
                    prompt_tokens, completion_tokens, total_tokens,
                    reasoning_tokens, prompt_cached_tokens,
                    prompt_cache_hit, prompt_cache_miss,
                    cost_yuan, error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    created_at,
                    workspace_root,
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
                    reasoning_tokens,
                    prompt_cached_tokens,
                    prompt_cache_hit,
                    prompt_cache_miss,
                    cost_yuan,
                    error,
                ),
            )

    # ═══════════════════════════════════════════════════════
    # 查询
    # ═══════════════════════════════════════════════════════

    _CALL_COLUMNS = """
        id, created_at, workspace_root, session_id, message_id,
        call_type, model, status, finish_reason, latency_ms,
        prompt_tokens, completion_tokens, total_tokens,
        reasoning_tokens, prompt_cached_tokens,
        prompt_cache_hit, prompt_cache_miss,
        cost_yuan, error
    """

    def list_calls(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        session_id: str | None = None,
        message_id: str | None = None,
        workspace_root: str | None = None,
    ) -> dict[str, Any]:
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        where, params = _where(session_id, message_id, workspace_root)
        sql = f"SELECT {self._CALL_COLUMNS} FROM llm_calls {where}"
        with self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM llm_calls {where}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"{sql} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            pricing = self._pricing_map(conn)
        return {
            "items": [
                self._call_row_with_current_cost(dict(row), pricing) for row in rows
            ],
            "pagination": {"limit": limit, "offset": offset, "total": total},
        }

    def series(
        self,
        *,
        span: str = "week",
        workspace_root: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        span = span if span in {"week", "month", "year"} else "week"
        bucket_expr = "strftime('%Y-%m', created_at)" if span == "year" else "date(created_at)"
        start_expr = {
            "week": "date('now', '-6 days')",
            "month": "date('now', '-29 days')",
            "year": "date('now', 'start of month', '-11 months')",
        }[span]

        clauses = [f"{bucket_expr} >= {start_expr}"]
        params: list[Any] = []
        if workspace_root:
            clauses.append("workspace_root = ?")
            params.append(workspace_root)
        if model:
            clauses.append("model = ?")
            params.append(model)
        where = "WHERE " + " AND ".join(clauses)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    {bucket_expr} AS bucket,
                    model,
                    COUNT(*) AS calls,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
                    COALESCE(SUM(prompt_cached_tokens), 0) AS cached_tokens
                FROM llm_calls
                {where}
                GROUP BY bucket, model
                ORDER BY bucket ASC, model ASC
                """,
                tuple(params),
            ).fetchall()
            models = conn.execute(
                "SELECT DISTINCT model FROM llm_calls ORDER BY model ASC"
            ).fetchall()
            pricing = self._pricing_map(conn)
        buckets = []
        for row in rows:
            prompt_tokens = row["prompt_tokens"] or 0
            completion_tokens = row["completion_tokens"] or 0
            reasoning_tokens = row["reasoning_tokens"] or 0
            cached_tokens = row["cached_tokens"] or 0
            output_tokens = max(completion_tokens - reasoning_tokens, 0)
            input_tokens = max(prompt_tokens - cached_tokens, 0)
            cost_yuan = self._cost_from_parts(
                row["model"],
                input_tokens=input_tokens,
                cached_tokens=cached_tokens,
                output_tokens=output_tokens,
                reasoning_tokens=reasoning_tokens,
                pricing=pricing,
            )
            buckets.append(
                {
                    "bucket": row["bucket"],
                    "model": row["model"],
                    "calls": row["calls"] or 0,
                    "input_tokens": input_tokens,
                    "cached_tokens": cached_tokens,
                    "output_tokens": output_tokens,
                    "reasoning_tokens": reasoning_tokens,
                    "total_tokens": input_tokens
                    + cached_tokens
                    + output_tokens
                    + reasoning_tokens,
                    "cost_yuan": _round(cost_yuan, 8) or 0,
                }
            )

        return {
            "span": span,
            "unit": "month" if span == "year" else "day",
            "models": [row["model"] for row in models],
            "buckets": buckets,
        }

    def summary(
        self,
        session_id: str | None = None,
        workspace_root: str | None = None,
    ) -> dict[str, Any]:
        where, params = _where(session_id=session_id, workspace_root=workspace_root)
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
                    COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
                    COALESCE(SUM(prompt_cached_tokens), 0) AS prompt_cached_tokens
                FROM llm_calls
                {where}
                """,
                params,
            ).fetchone()
            model_rows = conn.execute(
                f"""
                SELECT
                    model,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
                    COALESCE(SUM(prompt_cached_tokens), 0) AS cached_tokens
                FROM llm_calls
                {where}
                GROUP BY model
                """,
                params,
            ).fetchall()
            pricing = self._pricing_map(conn)
        cost_yuan = sum(self._aggregate_cost(row, pricing) for row in model_rows)
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
            "reasoning_tokens": row["reasoning_tokens"] or 0,
            "prompt_cached_tokens": row["prompt_cached_tokens"] or 0,
            "cost_yuan": _round(cost_yuan, 8),
        }

    def dashboard(
        self,
        *,
        limit: int = 20,
        session_id: str | None = None,
        workspace_root: str | None = None,
    ) -> dict[str, Any]:
        return {
            "summary": self.summary(
                session_id=session_id, workspace_root=workspace_root
            ),
            "by_model": self.by_model(
                session_id=session_id, workspace_root=workspace_root
            ),
            "recent_calls": self.list_calls(
                limit=limit,
                session_id=session_id,
                workspace_root=workspace_root,
            )["items"],
        }

    def by_model(
        self,
        session_id: str | None = None,
        workspace_root: str | None = None,
    ) -> list[dict[str, Any]]:
        where, params = _where(session_id=session_id, workspace_root=workspace_root)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    model,
                    COUNT(*) AS total_calls,
                    SUM(status = 'error') AS errored_calls,
                    AVG(latency_ms) AS avg_latency_ms,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
                    COALESCE(SUM(prompt_cached_tokens), 0) AS cached_tokens
                FROM llm_calls
                {where}
                GROUP BY model
                ORDER BY total_calls DESC, model ASC
                """,
                params,
            ).fetchall()
            pricing = self._pricing_map(conn)
        return [
            {
                "model": row["model"],
                "total_calls": row["total_calls"],
                "errored_calls": row["errored_calls"] or 0,
                "avg_latency_ms": _round(row["avg_latency_ms"]),
                "total_tokens": row["total_tokens"] or 0,
                "reasoning_tokens": row["reasoning_tokens"] or 0,
                "cost_yuan": _round(self._aggregate_cost(row, pricing), 8),
            }
            for row in rows
        ]

    # ═══════════════════════════════════════════════════════
    # model_pricing
    # ═══════════════════════════════════════════════════════

    def list_pricing(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT model_id, input_price_per_1m, output_price_per_1m, "
                "reasoning_price_per_1m, cached_input_price_per_1m, "
                "is_custom, updated_at "
                "FROM model_pricing ORDER BY model_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_pricing(
        self,
        model_id: str,
        input_price: float,
        output_price: float,
        reasoning_price: float | None = None,
        cached_input_price: float | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO model_pricing
                    (model_id, input_price_per_1m, output_price_per_1m,
                     reasoning_price_per_1m, cached_input_price_per_1m,
                     is_custom, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(model_id) DO UPDATE SET
                    input_price_per_1m = excluded.input_price_per_1m,
                    output_price_per_1m = excluded.output_price_per_1m,
                    reasoning_price_per_1m = excluded.reasoning_price_per_1m,
                    cached_input_price_per_1m = excluded.cached_input_price_per_1m,
                    is_custom = 1,
                    updated_at = excluded.updated_at
                """,
                (
                    model_id,
                    input_price,
                    output_price,
                    reasoning_price,
                    cached_input_price,
                    utc_now_iso(),
                ),
            )

    def delete_pricing(self, model_id: str) -> None:
        from app.core.config import get_settings
        s = get_settings()
        input_price = s.llm_input_cost_yuan_per_1m_tokens
        output_price = s.llm_output_cost_yuan_per_1m_tokens
        reasoning_price = s.llm_reasoning_cost_yuan_per_1m_tokens
        with self._lock, self._connect() as conn:
            has_calls = conn.execute(
                "SELECT 1 FROM llm_calls WHERE model = ? LIMIT 1", (model_id,)
            ).fetchone()
            if not has_calls:
                conn.execute(
                    "DELETE FROM model_pricing WHERE model_id = ? AND is_custom = 1",
                    (model_id,),
                )
                return
            conn.execute(
                """
                INSERT INTO model_pricing
                    (model_id, input_price_per_1m, output_price_per_1m,
                     reasoning_price_per_1m, cached_input_price_per_1m,
                     is_custom, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(model_id) DO UPDATE SET
                    input_price_per_1m = excluded.input_price_per_1m,
                    output_price_per_1m = excluded.output_price_per_1m,
                    reasoning_price_per_1m = excluded.reasoning_price_per_1m,
                    cached_input_price_per_1m = excluded.cached_input_price_per_1m,
                    is_custom = 0,
                    updated_at = excluded.updated_at
                """,
                (
                    model_id,
                    input_price,
                    output_price,
                    reasoning_price,
                    input_price,
                    utc_now_iso(),
                ),
            )

    # ═══════════════════════════════════════════════════════
    # 内部
    # ═══════════════════════════════════════════════════════

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS llm_calls (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    workspace_root TEXT DEFAULT '',
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
                CREATE INDEX IF NOT EXISTS idx_llm_calls_workspace
                    ON llm_calls(workspace_root);

                CREATE TABLE IF NOT EXISTS model_pricing (
                    model_id TEXT PRIMARY KEY,
                    input_price_per_1m REAL NOT NULL,
                    output_price_per_1m REAL NOT NULL,
                    reasoning_price_per_1m REAL,
                    cached_input_price_per_1m REAL,
                    is_custom INTEGER DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                """
            )
            # 兼容存量 DB 迁移
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(llm_calls)").fetchall()
            }
            migrations = [
                ("cost_yuan", "ALTER TABLE llm_calls ADD COLUMN cost_yuan REAL"),
                (
                    "workspace_root",
                    "ALTER TABLE llm_calls ADD COLUMN workspace_root TEXT DEFAULT ''",
                ),
                (
                    "reasoning_tokens",
                    "ALTER TABLE llm_calls ADD COLUMN reasoning_tokens INTEGER",
                ),
                (
                    "prompt_cached_tokens",
                    "ALTER TABLE llm_calls ADD COLUMN prompt_cached_tokens INTEGER",
                ),
                (
                    "prompt_cache_hit",
                    "ALTER TABLE llm_calls ADD COLUMN prompt_cache_hit INTEGER",
                ),
                (
                    "prompt_cache_miss",
                    "ALTER TABLE llm_calls ADD COLUMN prompt_cache_miss INTEGER",
                ),
            ]
            for col, sql in migrations:
                if col not in columns:
                    conn.execute(sql)
            pricing_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(model_pricing)").fetchall()
            }
            if "cached_input_price_per_1m" not in pricing_columns:
                conn.execute(
                    "ALTER TABLE model_pricing "
                    "ADD COLUMN cached_input_price_per_1m REAL"
                )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_pricing(self, model_id: str) -> None:
        """如果模型不在定价表中，用环境变量默认值自动插入。"""
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM model_pricing WHERE model_id = ?", (model_id,)
            ).fetchone()
            if exists:
                return
        from app.core.config import get_settings
        s = get_settings()
        input_price = s.llm_input_cost_yuan_per_1m_tokens
        output_price = s.llm_output_cost_yuan_per_1m_tokens
        reasoning_price = s.llm_reasoning_cost_yuan_per_1m_tokens
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO model_pricing
                    (model_id, input_price_per_1m, output_price_per_1m,
                     reasoning_price_per_1m, cached_input_price_per_1m,
                     is_custom, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    model_id,
                    input_price,
                    output_price,
                    reasoning_price,
                    input_price,
                    utc_now_iso(),
                ),
            )

    def _cost_yuan(
        self,
        model_id: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        reasoning_tokens: int | None = None,
        cached_tokens: int | None = None,
    ) -> float:
        with self._connect() as conn:
            pricing = self._pricing_map(conn)
        cache_hit = cached_tokens or 0
        cache_miss = max((prompt_tokens or 0) - cache_hit, 0)
        reasoning = reasoning_tokens or 0
        completion = max((completion_tokens or 0) - reasoning, 0)
        return self._cost_from_parts(
            model_id,
            input_tokens=cache_miss,
            cached_tokens=cache_hit,
            output_tokens=completion,
            reasoning_tokens=reasoning,
            pricing=pricing,
        )

    def _pricing_map(self, conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
        rows = conn.execute(
            "SELECT model_id, input_price_per_1m, output_price_per_1m, "
            "reasoning_price_per_1m, cached_input_price_per_1m "
            "FROM model_pricing"
        ).fetchall()
        return {row["model_id"]: dict(row) for row in rows}

    def _cost_from_parts(
        self,
        model_id: str,
        *,
        input_tokens: int,
        cached_tokens: int,
        output_tokens: int,
        reasoning_tokens: int,
        pricing: dict[str, dict[str, Any]],
    ) -> float:
        price = pricing.get(model_id) or {}
        input_price = price.get("input_price_per_1m")
        if input_price is None:
            from app.core.config import get_settings
            input_price = get_settings().llm_input_cost_yuan_per_1m_tokens
        output_price = price.get("output_price_per_1m")
        if output_price is None:
            from app.core.config import get_settings
            output_price = get_settings().llm_output_cost_yuan_per_1m_tokens
        reasoning_price = price.get("reasoning_price_per_1m")
        if reasoning_price is None:
            reasoning_price = output_price
        cached_price = price.get("cached_input_price_per_1m")
        if cached_price is None:
            cached_price = input_price
        return (
            input_tokens * input_price
            + cached_tokens * cached_price
            + output_tokens * output_price
            + reasoning_tokens * reasoning_price
        ) / 1_000_000

    def _aggregate_cost(
        self, row: sqlite3.Row, pricing: dict[str, dict[str, Any]]
    ) -> float:
        prompt_tokens = row["prompt_tokens"] or 0
        completion_tokens = row["completion_tokens"] or 0
        reasoning_tokens = row["reasoning_tokens"] or 0
        cached_tokens = row["cached_tokens"] or 0
        return self._cost_from_parts(
            row["model"],
            input_tokens=max(prompt_tokens - cached_tokens, 0),
            cached_tokens=cached_tokens,
            output_tokens=max(completion_tokens - reasoning_tokens, 0),
            reasoning_tokens=reasoning_tokens,
            pricing=pricing,
        )

    def _call_row_with_current_cost(
        self, row: dict[str, Any], pricing: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        prompt_tokens = row.get("prompt_tokens") or 0
        completion_tokens = row.get("completion_tokens") or 0
        reasoning_tokens = row.get("reasoning_tokens") or 0
        cached_tokens = row.get("prompt_cached_tokens") or 0
        row["cost_yuan"] = _round(
            self._cost_from_parts(
                row.get("model") or "",
                input_tokens=max(prompt_tokens - cached_tokens, 0),
                cached_tokens=cached_tokens,
                output_tokens=max(completion_tokens - reasoning_tokens, 0),
                reasoning_tokens=reasoning_tokens,
                pricing=pricing,
            ),
            8,
        )
        return row


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def usage_to_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return None


def _where(
    session_id: str | None = None,
    message_id: str | None = None,
    workspace_root: str | None = None,
) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if message_id:
        clauses.append("message_id = ?")
        params.append(message_id)
    if workspace_root:
        clauses.append("workspace_root = ?")
        params.append(workspace_root)
    if not clauses:
        return "", ()
    return "WHERE " + " AND ".join(clauses), tuple(params)


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _round(value: Any, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)
