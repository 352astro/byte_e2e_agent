"""memory 包 — 长期记忆存储与召回。

── 设计 ──
每条记忆 = side-query LLM 生成的摘要（纯文本）
检索 = SQLite FTS5 全文搜索（BM25）
零向量依赖，不依赖 embedding API 和 LanceDB。

内置实现:
- SQLiteMemoryStore: 持久化，FTS5 全文检索
- InMemoryMemoryStore: 纯内存，测试用
- MemoryHook: Hook 协议集成
"""

from agent.memory.memory_hook import MemoryHook
from agent.memory.store import (
    InMemoryMemoryStore,
    MemoryRecord,
    MemoryStore,
    SQLiteMemoryStore,
)

__all__ = [
    "InMemoryMemoryStore",
    "MemoryHook",
    "MemoryRecord",
    "MemoryStore",
    "SQLiteMemoryStore",
]
