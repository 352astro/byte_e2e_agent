"""Database — SQLite 数据库封装。

── 对标 ──
- Rust: persistence/db.rs

当前为轻量封装，完整迁移时会将 session.py 和 metrics.py 的 SQLite 逻辑收拢。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class Database:
    """SQLite 数据库封装（对标 Rust Database）。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        """创建数据库连接。"""
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def execute(self, sql: str, params: tuple = ()) -> None:
        """执行 SQL（不返回结果）。"""
        with self.connect() as conn:
            conn.execute(sql, params)

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        """查询并返回 dict 列表。"""
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def exists(self) -> bool:
        """检查数据库文件是否存在。"""
        return self.db_path.exists()
