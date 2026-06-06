"""链路 8: Persistence + Metrics — Database + Schema + SQLiteLLMMetricsStore。

测试范围:
- Database: 构造、connect、execute、query、exists
- SQLiteLLMMetricsStore: record_call、list_calls、summary、by_model、dashboard
- LLMCallContext: frozen dataclass, default values
- utc_now_iso: ISO 格式以 Z 结尾
- Schema: LLM_CALLS_SCHEMA 有效 SQL + ALL_SCHEMAS 类型校验
"""

from __future__ import annotations

import sqlite3
import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from agent.metrics import (
    LLMCallContext,
    SQLiteLLMMetricsStore,
    utc_now_iso,
)
from agent.persistence.db import Database
from agent.persistence.schema import ALL_SCHEMAS, LLM_CALLS_SCHEMA

# ═══════════════════════════════════════════════════════════
# Database
# ═══════════════════════════════════════════════════════════


class TestDatabase:
    """Database 类的单元测试。"""

    def test_constructor_creates_parent_directory(self):
        """构造 Database 时应自动创建父目录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_dir = Path(tmpdir) / "sub" / "nested"
            db_path = db_dir / "test.db"
            assert not db_dir.exists()
            Database(db_path)
            assert db_dir.exists()
            assert db_dir.is_dir()

    def test_connect_returns_connection_with_row_factory(self):
        """connect() 应返回 sqlite3.Connection，且 row_factory 为 sqlite3.Row。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            database = Database(db_path)
            conn = database.connect()
            assert isinstance(conn, sqlite3.Connection)
            assert conn.row_factory == sqlite3.Row
            conn.close()

    def test_connect_sets_wal_journal_mode(self):
        """connect() 应将 journal_mode 设为 WAL。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            database = Database(db_path)
            conn = database.connect()
            row = conn.execute("PRAGMA journal_mode").fetchone()
            # WAL mode may be reported as 'wal' (lowercase) depending on SQLite version
            assert row[0].lower() == "wal"
            conn.close()

    def test_execute_runs_sql(self):
        """execute() 应成功执行 DDL 和 DML。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            database = Database(db_path)
            database.execute(
                "CREATE TABLE IF NOT EXISTS test_table (id INTEGER PRIMARY KEY, name TEXT)"
            )
            database.execute("INSERT INTO test_table (id, name) VALUES (?, ?)", (1, "alice"))
            rows = database.query("SELECT * FROM test_table")
            assert len(rows) == 1
            assert rows[0]["name"] == "alice"

    def test_query_returns_list_of_dict(self):
        """query() 应返回 list[dict]，每行为 dict 格式。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            database = Database(db_path)
            database.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)")
            database.execute("INSERT INTO test_table (id, name) VALUES (?, ?)", (1, "bob"))
            database.execute("INSERT INTO test_table (id, name) VALUES (?, ?)", (2, "carol"))
            result = database.query("SELECT * FROM test_table ORDER BY id")
            assert isinstance(result, list)
            assert len(result) == 2
            assert all(isinstance(row, dict) for row in result)
            assert result[0] == {"id": 1, "name": "bob"}
            assert result[1] == {"id": 2, "name": "carol"}

    def test_query_with_params(self):
        """query() 应支持参数化查询。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            database = Database(db_path)
            database.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)")
            database.execute("INSERT INTO test_table (id, name) VALUES (?, ?)", (1, "dave"))
            database.execute("INSERT INTO test_table (id, name) VALUES (?, ?)", (2, "eve"))
            result = database.query("SELECT * FROM test_table WHERE name = ?", ("eve",))
            assert len(result) == 1
            assert result[0]["name"] == "eve"

    def test_exists_returns_true_when_file_present(self):
        """exists() 在数据库文件存在时返回 True。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            database = Database(db_path)
            # 执行一次操作以触发文件创建
            database.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY)")
            assert database.exists() is True

    def test_exists_returns_false_when_file_missing(self):
        """exists() 在数据库文件不存在时返回 False。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "nonexistent" / "test.db"
            database = Database(db_path)
            assert database.exists() is False


# ═══════════════════════════════════════════════════════════
# SQLiteLLMMetricsStore
# ═══════════════════════════════════════════════════════════


class TestSQLiteLLMMetricsStore:
    """SQLiteLLMMetricsStore 类的单元测试。"""

    # ── helpers ───────────────────────────────────────────

    @staticmethod
    def _make_store(tmpdir: str) -> SQLiteLLMMetricsStore:
        """在临时目录中创建 SQLiteLLMMetricsStore 实例。"""
        db_path = Path(tmpdir) / "metrics.db"
        return SQLiteLLMMetricsStore(db_path)

    @staticmethod
    def _record_sample(store: SQLiteLLMMetricsStore, **overrides) -> None:
        """便捷方法：使用默认值记录一次调用。"""
        defaults: dict = {
            "model": "gpt-4",
            "created_at": utc_now_iso(),
            "latency_ms": 500,
            "context": LLMCallContext(session_id="s1", message_id="t1"),
            "finish_reason": "stop",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }
        defaults.update(overrides)
        store.record_call(**defaults)

    # ── constructor ───────────────────────────────────────

    def test_constructor_creates_database_file(self):
        """构造 SQLiteLLMMetricsStore 时应创建数据库文件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "metrics.db"
            assert not db_path.exists()
            SQLiteLLMMetricsStore(db_path)
            assert db_path.exists()

    def test_constructor_initializes_llm_calls_table(self):
        """构造后 llm_calls 表应存在且包含预期列。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            conn = store._connect()
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(llm_calls)").fetchall()
            }
            expected_columns = {
                "id",
                "created_at",
                "session_id",
                "message_id",
                "call_type",
                "model",
                "status",
                "finish_reason",
                "latency_ms",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "cost_yuan",
                "error",
            }
            assert expected_columns <= columns
            conn.close()

    def test_constructor_creates_parent_directory(self):
        """即便父目录不存在，构造也应自动创建。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "deep" / "nested" / "metrics.db"
            assert not db_path.parent.exists()
            SQLiteLLMMetricsStore(db_path)
            assert db_path.parent.exists()

    # ── record_call ───────────────────────────────────────

    def test_record_call_inserts_a_row(self):
        """record_call() 应在 llm_calls 表中插入一行。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            self._record_sample(store, model="gpt-4o", latency_ms=1234)
            calls = store.list_calls()
            assert calls["pagination"]["total"] == 1
            item = calls["items"][0]
            assert item["model"] == "gpt-4o"
            assert item["latency_ms"] == 1234
            assert item["status"] == "success"
            assert item["session_id"] == "s1"
            assert item["message_id"] == "t1"
            assert item["call_type"] == "agent"
            assert item["finish_reason"] == "stop"

    def test_record_call_default_context(self):
        """record_call() 不传 context 时应使用默认 LLMCallContext。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            store.record_call(
                model="claude-3",
                created_at=utc_now_iso(),
                latency_ms=300,
            )
            calls = store.list_calls()
            item = calls["items"][0]
            assert item["call_type"] == "agent"
            assert item["session_id"] is None
            assert item["message_id"] is None

    def test_record_call_computes_cost_yuan(self):
        """record_call() 应根据 usage 计算 cost_yuan。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            store.record_call(
                model="gpt-4",
                created_at=utc_now_iso(),
                latency_ms=100,
                usage={"prompt_tokens": 1_000_000, "completion_tokens": 0},
            )
            calls = store.list_calls()
            item = calls["items"][0]
            # input_price defaults to 3.0 per 1M tokens
            assert item["cost_yuan"] == pytest.approx(3.0, rel=0.01)

    def test_cost_yuan_uses_current_pricing(self):
        """展示和汇总费用应按当前 model_pricing 动态重算。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            store.record_call(
                model="gpt-4",
                created_at=utc_now_iso(),
                latency_ms=100,
                usage={
                    "prompt_tokens": 1_000,
                    "completion_tokens": 2_000,
                    "total_tokens": 3_000,
                },
                reasoning_tokens=500,
                prompt_cached_tokens=200,
            )

            store.upsert_pricing(
                "gpt-4",
                input_price=10,
                output_price=20,
                reasoning_price=30,
                cached_input_price=1,
            )

            expected = (800 * 10 + 200 * 1 + 1_500 * 20 + 500 * 30) / 1_000_000
            assert store.list_calls()["items"][0]["cost_yuan"] == pytest.approx(expected)
            assert store.summary()["cost_yuan"] == pytest.approx(expected)
            assert store.series()["buckets"][0]["cost_yuan"] == pytest.approx(expected)

            store.upsert_pricing(
                "gpt-4",
                input_price=0,
                output_price=0,
                reasoning_price=0,
                cached_input_price=0,
            )
            assert store.summary()["cost_yuan"] == 0.0

    # ── error recording ───────────────────────────────────

    def test_record_call_with_error(self):
        """record_call(error=...) 时 status 应为 'error' 且 error 列存储错误信息。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            store.record_call(
                model="gpt-4",
                created_at=utc_now_iso(),
                latency_ms=50,
                error="Rate limit exceeded",
            )
            calls = store.list_calls()
            item = calls["items"][0]
            assert item["status"] == "error"
            assert item["error"] == "Rate limit exceeded"

    # ── list_calls pagination ─────────────────────────────

    def test_list_calls_returns_paginated_results(self):
        """list_calls() 应返回分页结构：items + pagination(limit/offset/total)。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            for i in range(15):
                self._record_sample(store, model=f"model-{i}", latency_ms=i * 10)
            result = store.list_calls(limit=10, offset=0)
            assert "items" in result
            assert "pagination" in result
            assert len(result["items"]) == 10
            assert result["pagination"]["limit"] == 10
            assert result["pagination"]["offset"] == 0
            assert result["pagination"]["total"] == 15

    def test_list_calls_offset_returns_remaining(self):
        """list_calls(offset=N) 应跳过前 N 条。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            for i in range(15):
                self._record_sample(store, model=f"model-{i}", latency_ms=i * 10)
            page1 = store.list_calls(limit=10, offset=0)
            page2 = store.list_calls(limit=10, offset=10)
            assert len(page2["items"]) == 5
            assert page2["pagination"]["offset"] == 10
            # 验证无重叠
            ids_p1 = {item["id"] for item in page1["items"]}
            ids_p2 = {item["id"] for item in page2["items"]}
            assert ids_p1.isdisjoint(ids_p2)

    def test_list_calls_clamps_limit(self):
        """list_calls() 应将 limit 限制在 1-500 之间。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            for _i in range(600):
                self._record_sample(store, model="m", latency_ms=1)
            # limit=0 → clamped to 1
            result_zero = store.list_calls(limit=0)
            assert len(result_zero["items"]) == 1
            # limit=1000 → clamped to 500
            result_big = store.list_calls(limit=1000)
            assert len(result_big["items"]) == 500

    # ── list_calls filtering ──────────────────────────────

    def test_list_calls_filters_by_session_id(self):
        """list_calls(session_id=...) 应仅返回该 session 的记录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            self._record_sample(
                store,
                model="m-a",
                context=LLMCallContext(session_id="ses_A"),
            )
            self._record_sample(
                store,
                model="m-b",
                context=LLMCallContext(session_id="ses_B"),
            )
            self._record_sample(
                store,
                model="m-c",
                context=LLMCallContext(session_id="ses_A"),
            )
            result = store.list_calls(session_id="ses_A")
            assert result["pagination"]["total"] == 2
            assert all(item["session_id"] == "ses_A" for item in result["items"])

    def test_list_calls_filter_unknown_session_returns_empty(self):
        """list_calls(session_id='nonexistent') 应返回空列表。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            self._record_sample(store, model="x")
            result = store.list_calls(session_id="no-such-session")
            assert result["pagination"]["total"] == 0
            assert result["items"] == []

    # ── summary ───────────────────────────────────────────

    def test_summary_returns_aggregate_stats(self):
        """summary() 应返回 total_calls、avg_latency_ms、tokens、cost 等字段。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            self._record_sample(
                store,
                model="gpt-4",
                latency_ms=100,
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
            self._record_sample(
                store,
                model="gpt-4",
                latency_ms=200,
                usage={
                    "prompt_tokens": 20,
                    "completion_tokens": 10,
                    "total_tokens": 30,
                },
            )
            s = store.summary()
            assert s["total_calls"] == 2
            assert s["successful_calls"] == 2
            assert s["errored_calls"] == 0
            assert s["avg_latency_ms"] == 150.0
            assert s["min_latency_ms"] == 100
            assert s["max_latency_ms"] == 200
            assert s["prompt_tokens"] == 30
            assert s["completion_tokens"] == 15
            assert s["total_tokens"] == 45
            assert isinstance(s["cost_yuan"], float)

    def test_summary_handles_empty_store(self):
        """summary() 在空数据库时应返回零值。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            s = store.summary()
            assert s["total_calls"] == 0
            assert s["successful_calls"] == 0
            assert s["errored_calls"] == 0
            assert s["avg_latency_ms"] is None
            assert s["total_tokens"] == 0
            assert s["cost_yuan"] == 0.0

    def test_summary_filters_by_session_id(self):
        """summary(session_id=...) 应仅聚合该 session 的数据。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            self._record_sample(
                store,
                model="m",
                context=LLMCallContext(session_id="sX"),
                latency_ms=10,
            )
            self._record_sample(
                store,
                model="m",
                context=LLMCallContext(session_id="sY"),
                latency_ms=20,
            )
            sx = store.summary(session_id="sX")
            assert sx["total_calls"] == 1
            assert sx["max_latency_ms"] == 10

    # ── by_model ──────────────────────────────────────────

    def test_by_model_groups_by_model(self):
        """by_model() 应按 model 分组返回统计。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            self._record_sample(store, model="gpt-4", latency_ms=100)
            self._record_sample(store, model="gpt-4", latency_ms=300)
            self._record_sample(store, model="claude-3", latency_ms=50)
            rows = store.by_model()
            assert len(rows) == 2
            # 按 total_calls DESC, model ASC 排序
            assert rows[0]["model"] == "gpt-4"
            assert rows[0]["total_calls"] == 2
            assert rows[1]["model"] == "claude-3"
            assert rows[1]["total_calls"] == 1

    def test_by_model_filters_by_session_id(self):
        """by_model(session_id=...) 应仅统计该 session。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            self._record_sample(
                store,
                model="m1",
                context=LLMCallContext(session_id="sA"),
            )
            self._record_sample(
                store,
                model="m2",
                context=LLMCallContext(session_id="sB"),
            )
            rows = store.by_model(session_id="sA")
            assert len(rows) == 1
            assert rows[0]["model"] == "m1"

    def test_by_model_empty_store(self):
        """by_model() 在空数据库时应返回空列表。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            assert store.by_model() == []

    # ── dashboard ─────────────────────────────────────────

    def test_dashboard_combines_summary_by_model_recent_calls(self):
        """dashboard() 应返回 summary + by_model + recent_calls 三部分。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            for i in range(5):
                self._record_sample(store, model=f"m-{i % 2}", latency_ms=10)
            d = store.dashboard(limit=3)
            assert "summary" in d
            assert "by_model" in d
            assert "recent_calls" in d
            assert d["summary"]["total_calls"] == 5
            assert len(d["by_model"]) == 2  # m-0 and m-1
            assert len(d["recent_calls"]) == 3  # limit=3

    def test_dashboard_session_id_propagates_to_summary(self):
        """dashboard(session_id=...) 应传递 session_id 到子查询。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            self._record_sample(
                store,
                model="x",
                context=LLMCallContext(session_id="alpha"),
            )
            self._record_sample(
                store,
                model="x",
                context=LLMCallContext(session_id="beta"),
            )
            d = store.dashboard(session_id="alpha")
            assert d["summary"]["total_calls"] == 1
            assert len(d["by_model"]) == 1
            assert len(d["recent_calls"]) == 1

    # ── multiple record_call ──────────────────────────────

    def test_multiple_record_call_then_verify_counts(self):
        """连续多次 record_call 后 count 应匹配。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            n = 42
            for _ in range(n):
                self._record_sample(store, model="bulk", latency_ms=1)
            assert store.summary()["total_calls"] == n
            calls = store.list_calls(limit=500)
            assert calls["pagination"]["total"] == n

    def test_mixed_success_and_error_counts(self):
        """混合记录 success 和 error 后 summary 应有正确计数。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._make_store(tmpdir)
            self._record_sample(store, model="ok", latency_ms=10)
            self._record_sample(store, model="ok", latency_ms=10)
            store.record_call(
                model="bad",
                created_at=utc_now_iso(),
                latency_ms=1,
                error="timeout",
            )
            s = store.summary()
            assert s["total_calls"] == 3
            assert s["successful_calls"] == 2
            assert s["errored_calls"] == 1


# ═══════════════════════════════════════════════════════════
# LLMCallContext
# ═══════════════════════════════════════════════════════════


class TestLLMCallContext:
    """LLMCallContext dataclass 的单元测试。"""

    def test_is_frozen_dataclass(self):
        """LLMCallContext 应是 frozen dataclass，不可原地修改。"""
        ctx = LLMCallContext()
        with pytest.raises(FrozenInstanceError):
            ctx.session_id = "hack"  # type: ignore[misc]

    def test_default_values(self):
        """默认构造的 LLMCallContext 应有预期默认值。"""
        ctx = LLMCallContext()
        assert ctx.session_id is None
        assert ctx.message_id is None
        assert ctx.call_type == "agent"

    def test_custom_values(self):
        """LLMCallContext 应支持传入自定义值。"""
        ctx = LLMCallContext(
            session_id="s1",
            message_id="t1",
            call_type="tool",
        )
        assert ctx.session_id == "s1"
        assert ctx.message_id == "t1"
        assert ctx.call_type == "tool"

    def test_partial_custom_values(self):
        """LLMCallContext 应支持部分参数覆盖。"""
        ctx = LLMCallContext(session_id="xyz")
        assert ctx.session_id == "xyz"
        assert ctx.message_id is None
        assert ctx.call_type == "agent"


# ═══════════════════════════════════════════════════════════
# utc_now_iso
# ═══════════════════════════════════════════════════════════


class TestUtcNowIso:
    """utc_now_iso 函数的单元测试。"""

    def test_returns_string(self):
        """utc_now_iso() 应返回字符串。"""
        result = utc_now_iso()
        assert isinstance(result, str)

    def test_ends_with_z(self):
        """utc_now_iso() 返回的 ISO 字符串应以 'Z' 结尾。"""
        result = utc_now_iso()
        assert result.endswith("Z"), f"Expected to end with 'Z', got: {result}"

    def test_no_plus_offset(self):
        """utc_now_iso() 不应包含 '+00:00' 时区偏移。"""
        result = utc_now_iso()
        assert "+00:00" not in result

    def test_no_minus_offset(self):
        """utc_now_iso() 不应包含 '-00:00' 时区偏移。"""
        result = utc_now_iso()
        assert "-00:00" not in result

    def test_contains_t_separator(self):
        """utc_now_iso() 应包含 ISO 的 'T' 分隔符。"""
        result = utc_now_iso()
        assert "T" in result

    def test_length_in_reasonable_range(self):
        """utc_now_iso() 返回的字符串长度应在合理范围（约 20-30 字符）。"""
        result = utc_now_iso()
        assert 20 <= len(result) <= 30


# ═══════════════════════════════════════════════════════════
# Schema
# ═══════════════════════════════════════════════════════════


class TestSchema:
    """Schema 定义的单元测试。"""

    def test_llm_calls_schema_is_valid_sql(self):
        """LLM_CALLS_SCHEMA 应是有效 SQL（可被 SQLite 执行）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_schema.db"
            conn = sqlite3.connect(str(db_path))
            try:
                conn.executescript(LLM_CALLS_SCHEMA)
                # 验证表已创建
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                table_names = [t[0] for t in tables]
                assert "llm_calls" in table_names
                # 验证索引已创建
                indexes = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
                index_names = [i[0] for i in indexes]
                assert "idx_llm_calls_created_at" in index_names
                assert "idx_llm_calls_session_id" in index_names
            finally:
                conn.close()

    def test_llm_calls_schema_idempotent(self):
        """LLM_CALLS_SCHEMA 应是幂等的（多次执行不报错）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_schema.db"
            conn = sqlite3.connect(str(db_path))
            try:
                conn.executescript(LLM_CALLS_SCHEMA)
                # 第二次执行不应抛异常
                conn.executescript(LLM_CALLS_SCHEMA)
            finally:
                conn.close()

    def test_all_schemas_is_list_of_strings(self):
        """ALL_SCHEMAS 应是 list[str] 类型。"""
        assert isinstance(ALL_SCHEMAS, list)
        assert len(ALL_SCHEMAS) > 0
        for schema in ALL_SCHEMAS:
            assert isinstance(schema, str), f"Expected str, got {type(schema)}"

    def test_all_schemas_elements_are_valid_sql(self):
        """ALL_SCHEMAS 中每个元素应是有效 SQL。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_all_schemas.db"
            conn = sqlite3.connect(str(db_path))
            try:
                for schema in ALL_SCHEMAS:
                    conn.executescript(schema)
            finally:
                conn.close()

    def test_all_schemas_contains_expected_schemas(self):
        """ALL_SCHEMAS 应包含 LLM_CALLS_SCHEMA、SESSION_MESSAGES_SCHEMA、SESSION_CONFIG_SCHEMA。"""
        assert LLM_CALLS_SCHEMA in ALL_SCHEMAS
        # 确认共 3 个 schema
        assert len(ALL_SCHEMAS) == 3
