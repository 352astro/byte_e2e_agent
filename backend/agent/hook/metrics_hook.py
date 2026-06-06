"""MetricsHook — 将 LLM 调用指标写入 SQLite。

记录每次 LLM 调用的完整 metrics：tokens（含 reasoning/cache）、延迟、费用。
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from shared.hooks import BaseHook
from shared.types import Message

if TYPE_CHECKING:
    from agent.metrics import SQLiteLLMMetricsStore

logger = logging.getLogger(__name__)


class MetricsHook(BaseHook):
    """记录 LLM 调用指标到 SQLite。

    用法:
        store = SQLiteLLMMetricsStore("/path/to/metrics.db")
        hook = MetricsHook(store, workspace_root="/path/to/project")
    """

    def __init__(
        self,
        store: SQLiteLLMMetricsStore,
        model_id: str = "",
        workspace_root: str = "",
    ) -> None:
        self._store = store
        self._model_id = model_id
        self._workspace_root = workspace_root
        self._start_times: dict[str, float] = {}

    # ═══════════════════════════════════════════════════════
    # BaseHook 实现
    # ═══════════════════════════════════════════════════════

    async def on_message_start(self, *, msg: Message, **kwargs: Any) -> None:
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
        session_id: str = "",
        **kwargs: Any,
    ) -> None:
        message_id = msg.id
        _usage = usage or {}
        _model_id = model_id or self._model_id

        start_time = self._start_times.pop(message_id, None)
        _latency_ms = latency_ms
        if start_time is not None and _latency_ms == 0:
            _latency_ms = int((time.perf_counter() - start_time) * 1000)

        # 提取扩展字段
        details = _usage.get("completion_tokens_details") or {}
        prompt_details = _usage.get("prompt_tokens_details") or {}
        reasoning_tokens = _int(details.get("reasoning_tokens"))
        prompt_cached_tokens = _int(prompt_details.get("cached_tokens"))
        prompt_cache_hit = _int(_usage.get("prompt_cache_hit_tokens"))
        prompt_cache_miss = _int(_usage.get("prompt_cache_miss_tokens"))

        try:
            from agent.metrics import LLMCallContext, utc_now_iso

            self._store.record_call(
                model=_model_id,
                created_at=utc_now_iso(),
                latency_ms=_latency_ms,
                workspace_root=self._workspace_root,
                context=LLMCallContext(
                    session_id=session_id,
                    message_id=message_id,
                    call_type="agent_step",
                ),
                finish_reason=finish_reason or None,
                usage=_usage,
                reasoning_tokens=reasoning_tokens,
                prompt_cached_tokens=prompt_cached_tokens,
                prompt_cache_hit=prompt_cache_hit,
                prompt_cache_miss=prompt_cache_miss,
            )
        except Exception:
            logger.exception("MetricsHook: failed to record LLM call")

    async def on_message_error(
        self,
        *,
        msg: Message,
        error: Exception,
        session_id: str = "",
        **kwargs: Any,
    ) -> None:
        message_id = msg.id

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
                workspace_root=self._workspace_root,
                context=LLMCallContext(
                    session_id=session_id,
                    message_id=message_id,
                    call_type="agent_step",
                ),
                error=str(error) if error else "Unknown error",
            )
        except Exception:
            logger.exception("MetricsHook: failed to record LLM error")


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except TypeError, ValueError:
        return None
