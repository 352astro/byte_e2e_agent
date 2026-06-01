"""hook 包 — 内置 Hook 实现。

对标 Rust byte_e2e_agent_rs/src/core/hook/ 的公开 API。

内置 Hook:
- StreamDriverHook   → SSE 推送
- MetricsHook        → SQLite 指标
- LoggingHook        → 彩色控制台输出
- ShadowCommitHook   → Message 生命周期触发 workspace 快照
- PersistenceHook    → Message 持久化到 JSONL
- MemoryHook         → 长期记忆存储与召回（来自 agent.memory）
"""

from agent.hook.logging_hook import LoggingHook
from agent.hook.metrics_hook import MetricsHook
from agent.hook.persistence_hook import PersistenceHook
from agent.hook.shadow_commit_hook import ShadowCommitHook
from agent.hook.stream_driver import StreamDriverHook
from agent.memory import MemoryHook

__all__ = [
    "LoggingHook",
    "MemoryHook",
    "MetricsHook",
    "PersistenceHook",
    "ShadowCommitHook",
    "StreamDriverHook",
]
