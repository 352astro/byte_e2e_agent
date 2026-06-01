"""memory 包 — 长期记忆存储与召回。

── 设计 ──
每条记忆 = side-query LLM 生成的正文 + 简短特征描述
检索 = SQLite scope 粗筛 + LLM 基于特征描述挑选
零向量依赖，不依赖 embedding API 和 LanceDB。

内置实现:
- SQLiteMemoryStore: 持久化、去重、scope/kind 粗筛
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
