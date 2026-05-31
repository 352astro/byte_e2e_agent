"""数据库 Schema 定义。

── 对标 ──
- Rust: persistence/schema.rs

当前定义表结构，完整迁移时用于 Database 初始化。
"""

# ── LLM Call 指标表 ──────────────────────────────────────

LLM_CALLS_SCHEMA = """
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

# ── Session Messages 表（规划中）──────────────────────────

SESSION_MESSAGES_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    tool_calls TEXT,         -- JSON
    tool_call_id TEXT,
    tool_name TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session
    ON messages(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_messages_turn
    ON messages(turn_id);
"""

# ── Session 配置表（规划中）───────────────────────────────

SESSION_CONFIG_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_configs (
    session_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    model_id TEXT NOT NULL,
    preamble TEXT DEFAULT '',
    tool_set TEXT DEFAULT 'all',
    config_json TEXT NOT NULL,  -- 完整 JSON 备份
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# ── 所有 Schema 汇总 ─────────────────────────────────────

ALL_SCHEMAS = [
    LLM_CALLS_SCHEMA,
    SESSION_MESSAGES_SCHEMA,
    SESSION_CONFIG_SCHEMA,
]
