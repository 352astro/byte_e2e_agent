"""Long-term memory store abstractions and SQLite FTS5 implementation."""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

MEMORY_SCOPES = {"session", "workspace", "project", "user"}
MEMORY_KINDS = {"fact", "preference", "decision", "todo", "summary"}


@dataclass
class MemoryRecord:
    """A structured long-term memory item."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    workspace: str = ""
    session_id: str = ""
    turn_id: str = ""
    scope: str = "workspace"
    kind: str = "summary"
    content: str = ""
    feature: str = ""
    confidence: float = 1.0
    content_hash: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_used_at: float | None = None
    use_count: int = 0
    archived: bool = False


class MemoryStore(ABC):
    """Long-term memory storage abstraction."""

    @abstractmethod
    async def add(self, record: MemoryRecord) -> None:
        """Store or update one memory."""
        ...

    @abstractmethod
    async def list(
        self,
        *,
        workspace: str | None = None,
        scopes: tuple[str, ...] | None = None,
        kinds: tuple[str, ...] | None = None,
        limit: int = 200,
    ) -> list[MemoryRecord]:
        """List memories by recency."""
        ...

    @abstractmethod
    async def delete(self, memory_id: str, *, workspace: str | None = None) -> bool:
        """Delete one memory by id."""
        ...

    @abstractmethod
    async def mark_used(self, memory_ids: list[str]) -> None:
        """Mark selected memories as used."""
        ...

    @abstractmethod
    async def search(
        self,
        query: str,
        top_k: int = 5,
        session_id: str | None = None,
        workspace: str | None = None,
        scopes: tuple[str, ...] | None = None,
        kinds: tuple[str, ...] | None = None,
    ) -> list[MemoryRecord]:
        """Search memories by keyword using FTS5 BM25."""
        ...

    @abstractmethod
    async def delete_session(self, session_id: str) -> None:
        """Delete session-scoped memories for a session."""
        ...

    @abstractmethod
    async def count(self, session_id: str | None = None) -> int:
        """Return memory count."""
        ...


_CJK_RANGES = [
    (0x4E00, 0x9FFF),
    (0x3400, 0x4DBF),
    (0xF900, 0xFAFF),
]


def _split_cjk(text: str) -> str:
    chars: list[str] = []
    for ch in text:
        cp = ord(ch)
        is_cjk = any(lo <= cp <= hi for lo, hi in _CJK_RANGES)
        chars.append(f" {ch} " if is_cjk else ch)
    return "".join(chars)


def _is_cjk_char(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def _query_terms(query: str) -> list[str]:
    """Tokenize mixed English/CJK query for broad FTS recall."""
    terms: list[str] = []
    for word in re.findall(r"[A-Za-z0-9_./:-]+", query):
        if len(word) >= 2:
            terms.append(word)
    for ch in query:
        if _is_cjk_char(ch):
            terms.append(ch)
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        result.append(term)
    return result


def _unsplit_cjk(text: str) -> str:
    lo = chr(0x4E00)
    hi = chr(0x9FFF)
    la = chr(0x3400)
    ha = chr(0x4DBF)
    lc = chr(0xF900)
    hc = chr(0xFAFF)
    cjk = "[" + lo + "-" + hi + la + "-" + ha + lc + "-" + hc + "]"
    while True:
        new_text = re.sub("(" + cjk + ") +(" + cjk + ")", r"\1\2", text)
        if new_text == text:
            break
        text = new_text
    text = re.sub(r" +([，。！？；：、）】》」』])", r"\1", text)
    text = re.sub(r"([（【《「『]) +", r"\1", text)
    return re.sub(r"  +", " ", text).strip()


def memory_content_hash(content: str) -> str:
    normalized = " ".join(content.strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    workspace TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'workspace',
    kind TEXT NOT NULL DEFAULT 'summary',
    content TEXT NOT NULL,
    feature TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 1.0,
    content_hash TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_used_at REAL,
    use_count INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    content=memories,
    content_rowid=rowid,
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content)
    VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
    INSERT INTO memories_fts(rowid, content)
    VALUES (new.rowid, new.content);
END;

CREATE INDEX IF NOT EXISTS idx_memories_workspace_scope
    ON memories(workspace, scope, archived);
CREATE INDEX IF NOT EXISTS idx_memories_session
    ON memories(session_id, archived);
CREATE INDEX IF NOT EXISTS idx_memories_hash
    ON memories(workspace, scope, kind, content_hash);
"""


class SQLiteMemoryStore(MemoryStore):
    """SQLite FTS5 persistent memory store.

    Stored at ``PROJECT_ROOT/.agent/workspaces/{uuid}/memory.db``.
    """

    def __init__(self, workspace_uuid: str) -> None:
        from agent.paths import workspace_data_dir

        self._workspace_uuid = workspace_uuid
        self._db_path = workspace_data_dir(workspace_uuid) / "memory.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.executescript(_SCHEMA)
            self._migrate_existing()
        return self._conn

    def _migrate_existing(self) -> None:
        conn = self._conn
        assert conn is not None
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(memories)").fetchall()
        }
        additions = {
            "workspace": "TEXT NOT NULL DEFAULT ''",
            "scope": "TEXT NOT NULL DEFAULT 'workspace'",
            "kind": "TEXT NOT NULL DEFAULT 'summary'",
            "confidence": "REAL NOT NULL DEFAULT 1.0",
            "feature": "TEXT NOT NULL DEFAULT ''",
            "content_hash": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "REAL NOT NULL DEFAULT 0",
            "last_used_at": "REAL",
            "use_count": "INTEGER NOT NULL DEFAULT 0",
            "archived": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, spec in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {spec}")
        now = time.time()
        conn.execute(
            "UPDATE memories SET workspace = ? WHERE workspace = ''",
            (self._workspace_uuid,),
        )
        conn.execute("UPDATE memories SET updated_at = ? WHERE updated_at = 0", (now,))
        rows = conn.execute(
            "SELECT id, content FROM memories WHERE content_hash = ''"
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE memories SET content_hash = ? WHERE id = ?",
                (memory_content_hash(_unsplit_cjk(row["content"])), row["id"]),
            )
        conn.execute("UPDATE memories SET feature = content WHERE feature = ''")
        conn.execute(
            "UPDATE memories SET scope = 'workspace' "
            "WHERE scope = 'session' "
            "AND kind IN ('fact', 'preference', 'decision', 'todo')"
        )
        conn.commit()

    async def add(self, record: MemoryRecord) -> None:
        conn = self._get_conn()
        now = time.time()
        content = record.content.strip()
        if not content:
            return
        feature = (record.feature or content).strip()
        scope = record.scope if record.scope in MEMORY_SCOPES else "workspace"
        kind = record.kind if record.kind in MEMORY_KINDS else "summary"
        workspace = record.workspace or self._workspace_uuid
        content_hash = record.content_hash or memory_content_hash(content)
        try:
            existing = conn.execute(
                "SELECT id, use_count FROM memories "
                "WHERE workspace = ? AND scope = ? AND kind = ? "
                "AND content_hash = ? AND archived = 0 "
                "LIMIT 1",
                (workspace, scope, kind, content_hash),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE memories SET session_id = ?, turn_id = ?, content = ?, "
                    "feature = ?, confidence = ?, updated_at = ?, use_count = ? "
                    "WHERE id = ?",
                    (
                        record.session_id,
                        record.turn_id,
                        _split_cjk(content),
                        _split_cjk(feature),
                        record.confidence,
                        now,
                        int(existing["use_count"] or 0) + 1,
                        existing["id"],
                    ),
                )
            else:
                conn.execute(
                    "INSERT INTO memories ("
                    "id, workspace, session_id, turn_id, scope, kind, content, "
                    "feature, confidence, content_hash, created_at, updated_at, "
                    "last_used_at, use_count, archived"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.id,
                        workspace,
                        record.session_id,
                        record.turn_id,
                        scope,
                        kind,
                        _split_cjk(content),
                        _split_cjk(feature),
                        record.confidence,
                        content_hash,
                        record.created_at or now,
                        record.updated_at or now,
                        record.last_used_at,
                        record.use_count,
                        int(record.archived),
                    ),
                )
            conn.commit()
        except Exception:
            logger.exception("SQLiteMemoryStore: add failed")

    async def search(
        self,
        query: str,
        top_k: int = 5,
        session_id: str | None = None,
        workspace: str | None = None,
        scopes: tuple[str, ...] | None = None,
        kinds: tuple[str, ...] | None = None,
    ) -> list[MemoryRecord]:
        conn = self._get_conn()
        if not query.strip():
            return []
        terms = _query_terms(query)
        if not terms:
            return []

        fts_query = " OR ".join(f'"{_split_cjk(t)}"' for t in terms)
        where = ["memories_fts MATCH ?", "m.archived = 0"]
        params: list[object] = [fts_query]
        if workspace:
            where.append("m.workspace = ?")
            params.append(workspace)
        if scopes:
            placeholders = ", ".join("?" for _ in scopes)
            where.append(f"m.scope IN ({placeholders})")
            params.extend(scopes)
        if kinds:
            placeholders = ", ".join("?" for _ in kinds)
            where.append(f"m.kind IN ({placeholders})")
            params.extend(kinds)
        if session_id:
            where.append("(m.scope != 'session' OR m.session_id = ?)")
            params.append(session_id)

        params.append(top_k)
        sql = (
            "SELECT m.id, m.workspace, m.session_id, m.turn_id, m.scope, "
            "m.kind, m.content, m.feature, m.confidence, m.content_hash, m.created_at, "
            "m.updated_at, m.last_used_at, m.use_count, m.archived, "
            "bm25(memories_fts) AS score "
            "FROM memories_fts "
            "JOIN memories m ON m.rowid = memories_fts.rowid "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY score LIMIT ?"
        )
        try:
            rows = conn.execute(sql, tuple(params)).fetchall()
            if rows:
                now = time.time()
                conn.executemany(
                    "UPDATE memories SET last_used_at = ?, use_count = use_count + 1 "
                    "WHERE id = ?",
                    [(now, row["id"]) for row in rows],
                )
                conn.commit()
        except Exception:
            logger.exception("SQLiteMemoryStore: search failed")
            return []

        return [_record_from_row(row) for row in rows]

    async def list(
        self,
        *,
        workspace: str | None = None,
        scopes: tuple[str, ...] | None = None,
        kinds: tuple[str, ...] | None = None,
        limit: int = 200,
    ) -> list[MemoryRecord]:
        conn = self._get_conn()
        where = ["archived = 0"]
        params: list[object] = []
        if workspace:
            where.append("workspace = ?")
            params.append(workspace)
        if scopes:
            placeholders = ", ".join("?" for _ in scopes)
            where.append(f"scope IN ({placeholders})")
            params.extend(scopes)
        if kinds:
            placeholders = ", ".join("?" for _ in kinds)
            where.append(f"kind IN ({placeholders})")
            params.extend(kinds)
        params.append(limit)
        sql = (
            "SELECT id, workspace, session_id, turn_id, scope, kind, content, feature, "
            "confidence, content_hash, created_at, updated_at, last_used_at, "
            "use_count, archived FROM memories "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY updated_at DESC, created_at DESC LIMIT ?"
        )
        try:
            rows = conn.execute(sql, tuple(params)).fetchall()
        except Exception:
            logger.exception("SQLiteMemoryStore: list failed")
            return []
        return [_record_from_row(row) for row in rows]

    async def delete(self, memory_id: str, *, workspace: str | None = None) -> bool:
        conn = self._get_conn()
        try:
            if workspace:
                cur = conn.execute(
                    "DELETE FROM memories WHERE id = ? AND workspace = ?",
                    (memory_id, workspace),
                )
            else:
                cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.commit()
            return cur.rowcount > 0
        except Exception:
            logger.exception("SQLiteMemoryStore: delete failed")
            return False

    async def mark_used(self, memory_ids: list[str]) -> None:
        ids = [memory_id for memory_id in memory_ids if memory_id]
        if not ids:
            return
        conn = self._get_conn()
        now = time.time()
        try:
            conn.executemany(
                "UPDATE memories SET last_used_at = ?, use_count = use_count + 1 "
                "WHERE id = ? AND archived = 0",
                [(now, memory_id) for memory_id in ids],
            )
            conn.commit()
        except Exception:
            logger.exception("SQLiteMemoryStore: mark_used failed")

    async def delete_session(self, session_id: str) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                "DELETE FROM memories WHERE session_id = ? AND scope = 'session'",
                (session_id,),
            )
            conn.commit()
        except Exception:
            logger.exception("SQLiteMemoryStore: delete_session failed")

    async def count(self, session_id: str | None = None) -> int:
        conn = self._get_conn()
        try:
            if session_id:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM memories "
                    "WHERE session_id = ? AND archived = 0",
                    (session_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM memories WHERE archived = 0"
                ).fetchone()
            return int(row["n"]) if row else 0
        except Exception:
            logger.exception("SQLiteMemoryStore: count failed")
            return 0


def _record_from_row(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        workspace=row["workspace"],
        session_id=row["session_id"],
        turn_id=row["turn_id"],
        scope=row["scope"],
        kind=row["kind"],
        content=_unsplit_cjk(row["content"]),
        feature=_unsplit_cjk(row["feature"]),
        confidence=float(row["confidence"]),
        content_hash=row["content_hash"],
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        last_used_at=row["last_used_at"],
        use_count=int(row["use_count"]),
        archived=bool(row["archived"]),
    )


class InMemoryMemoryStore(MemoryStore):
    """In-memory implementation for tests."""

    def __init__(self) -> None:
        self._records: list[MemoryRecord] = []

    async def add(self, record: MemoryRecord) -> None:
        if not record.content_hash:
            record.content_hash = memory_content_hash(record.content)
        for idx, existing in enumerate(self._records):
            if (
                existing.workspace == record.workspace
                and existing.scope == record.scope
                and existing.kind == record.kind
                and existing.content_hash == record.content_hash
                and not existing.archived
            ):
                record.use_count = existing.use_count + 1
                record.created_at = existing.created_at
                self._records[idx] = record
                return
        self._records.append(record)

    async def search(
        self,
        query: str,
        top_k: int = 5,
        session_id: str | None = None,
        workspace: str | None = None,
        scopes: tuple[str, ...] | None = None,
        kinds: tuple[str, ...] | None = None,
    ) -> list[MemoryRecord]:
        terms = query.strip().lower().split()
        if not terms:
            return []
        scored: list[tuple[MemoryRecord, int]] = []
        for rec in self._records:
            if rec.archived:
                continue
            if workspace and rec.workspace != workspace:
                continue
            if scopes and rec.scope not in scopes:
                continue
            if kinds and rec.kind not in kinds:
                continue
            if session_id and rec.scope == "session" and rec.session_id != session_id:
                continue
            content_lower = rec.content.lower()
            score = sum(1 for term in terms if term in content_lower)
            if score > 0:
                scored.append((rec, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return [record for record, _ in scored[:top_k]]

    async def list(
        self,
        *,
        workspace: str | None = None,
        scopes: tuple[str, ...] | None = None,
        kinds: tuple[str, ...] | None = None,
        limit: int = 200,
    ) -> list[MemoryRecord]:
        records = [
            rec
            for rec in self._records
            if not rec.archived
            and (not workspace or rec.workspace == workspace)
            and (not scopes or rec.scope in scopes)
            and (not kinds or rec.kind in kinds)
        ]
        records.sort(key=lambda rec: (rec.updated_at, rec.created_at), reverse=True)
        return records[:limit]

    async def delete(self, memory_id: str, *, workspace: str | None = None) -> bool:
        before = len(self._records)
        self._records = [
            rec
            for rec in self._records
            if not (
                rec.id == memory_id
                and (workspace is None or rec.workspace == workspace)
            )
        ]
        return len(self._records) != before

    async def mark_used(self, memory_ids: list[str]) -> None:
        ids = {memory_id for memory_id in memory_ids if memory_id}
        if not ids:
            return
        now = time.time()
        for rec in self._records:
            if rec.id in ids and not rec.archived:
                rec.last_used_at = now
                rec.use_count += 1

    async def delete_session(self, session_id: str) -> None:
        self._records = [
            r
            for r in self._records
            if not (r.session_id == session_id and r.scope == "session")
        ]

    async def count(self, session_id: str | None = None) -> int:
        if session_id is None:
            return sum(1 for r in self._records if not r.archived)
        return sum(
            1 for r in self._records if r.session_id == session_id and not r.archived
        )
