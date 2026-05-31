"""MetricsHook — 将 LLM 调用指标写入 SQLite。

── 职责 ──
- 替代当前 llm.py 中硬编码的 metrics_store.record_call() 调用
- 在 on_llm_end 时记录一次完整的 LLM 调用指标

── 对标 ──
- LangChain: 无直接对标（LangChain 的 metrics 通常集成在 tracer 中）
- 这里作为独立 Hook，可插拔
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from shared.hooks import BaseHook
from shared.types import Message

if TYPE_CHECKING:
    from agent.metrics import LLMCallContext, SQLiteLLMMetricsStore

logger = logging.getLogger(__name__)


class MetricsHook(BaseHook):
    """记录 LLM 调用指标到 SQLite。

    在 on_llm_end 时记录一次完整调用（模型、延迟、token 用量、费用）。

    用法:
        from agent.metrics import SQLiteLLMMetricsStore
        store = SQLiteLLMMetricsStore("/path/to/metrics.db")
        hook = MetricsHook(store)
        hooks = HookManager([hook, ...])
    """

    def __init__(
        self,
        store: "SQLiteLLMMetricsStore",
        model_id: str = "",
    ) -> None:
        self._store = store
        self._model_id = model_id
        # 跟踪每个 message_id 的开始时间
        self._start_times: dict[str, float] = {}

    # ═══════════════════════════════════════════════════════
    # BaseHook 实现
    # ═══════════════════════════════════════════════════════

    async def on_message_start(self, *, msg: Message, **kwargs: Any) -> None:
        """记录 LLM 调用开始时间。"""
        if msg.id:
            self._start_times[msg.id] = time.perf_counter()

    async def on_message_finish(
        self,
        *,
        msg: Message,
        finish_reason: str = "",
        usage: dict | None = None,
        latency_ms: int = 0,
        model_id: str = "",
        **kwargs: Any,
    ) -> None:
        """记录 LLM 调用完成指标。"""
        message_id = msg.id
        _usage = usage or {}
        turn_id = msg.turn_id
        _model_id = model_id or self._model_id

        start_time = self._start_times.pop(message_id, None)
        _latency_ms = latency_ms
        if start_time is not None and _latency_ms == 0:
            _latency_ms = int((time.perf_counter() - start_time) * 1000)

        try:
            from agent.metrics import LLMCallContext, utc_now_iso

            self._store.record_call(
                model=_model_id,
                created_at=utc_now_iso(),
                latency_ms=_latency_ms,
                context=LLMCallContext(
                    session_id=turn_id,  # 近似映射：turn_id → session_id
                    message_id=message_id,
                    call_type="agent_step",
                ),
                finish_reason=finish_reason or None,
                usage=_usage,
            )
        except Exception:
            logger.exception("MetricsHook: failed to record LLM call")

    async def on_message_error(
        self,
        *,
        msg: Message,
        error: Exception,
        **kwargs: Any,
    ) -> None:
        """记录 LLM 调用错误。"""
        message_id = msg.id
        turn_id = msg.turn_id

        start_time = self._start_times.pop(message_id, None)
        latency_ms = 0
        if start_time is not None:
            latency_ms = int((time.perf_counter() - start_time) * 1000)

        try:
            from agent.metrics import LLMCallContext, utc_now_iso

            self._store.record_call(
                model=self._model_id,
                created_at=utc_now_iso(),
                latency_ms=latency_ms,
                context=LLMCallContext(
                    session_id=turn_id,
                    message_id=message_id,
                    call_type="agent_step",
                ),
                error=str(error) if error else "Unknown error",
            )
        except Exception:
            logger.exception("MetricsHook: failed to record LLM error")
