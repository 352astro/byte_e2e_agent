"""Hook 基础设施 — 不属于 agent 编排逻辑，属于共享基础设施。

── 设计 ──
- BaseHook 对标 LangChain BaseCallbackHandler
- HookManager 对标 LangChain CallbackManager
- 主循环拥有数据，Hook 只收通知
- Hook 抛异常不影响主循环和其他 Hook
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC
from typing import Any

from shared.types import Message

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# BaseHook
# ═══════════════════════════════════════════════════════════


class BaseHook(ABC):
    """所有 Hook 的基类。每个方法默认 no-op，子类按需重写。"""

    # ── Message 生命周期 ─────────────────────────────────

    async def on_message_start(self, *, msg: Message, **kwargs: Any) -> None:
        """新 Message 开始构建。"""
        pass

    async def on_chunk_delta(
        self,
        *,
        msg: Message,
        field: str,
        delta: str,
        tool_name: str = "",
        **kwargs: Any,
    ) -> None:
        """Message 字段追加增量。field 是 Message 属性名。"""
        pass

    async def on_chunk_complete(
        self,
        *,
        msg: Message,
        field: str,
        full_content: str,
        tool_name: str = "",
        tool_args: str = "",
        is_error: bool = False,
        **kwargs: Any,
    ) -> None:
        """结构化字段（tool_calls/tool_result）一次性完成。"""
        pass

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
        """Message 构建完成。"""
        pass

    async def on_message_error(
        self,
        *,
        msg: Message,
        error: Exception,
        **kwargs: Any,
    ) -> None:
        """Message 构建出错。"""
        pass

    # ── Turn 生命周期 ────────────────────────────────────

    async def on_turn_start(
        self,
        *,
        turn_id: str,
        session_id: str,
        user_question: str = "",
        **kwargs: Any,
    ) -> None:
        """Turn 开始。"""
        pass

    async def on_turn_end(
        self,
        *,
        turn_id: str,
        session_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        **kwargs: Any,
    ) -> None:
        """Turn 结束。"""
        pass

    # ── SubAgent 生命周期 ────────────────────────────────

    async def on_subagent_start(
        self,
        *,
        task: str,
        parent_session_id: str,
        max_steps: int = 0,
        **kwargs: Any,
    ) -> None:
        pass

    async def on_subagent_end(self, *, result: str, **kwargs: Any) -> None:
        pass


# ═══════════════════════════════════════════════════════════
# HookManager
# ═══════════════════════════════════════════════════════════


class HookManager:
    """管理多个 Hook 实例，并行分发事件。

    - 每个 hook 独立 asyncio task
    - 单个 hook 抛异常不影响其他 hook 和主循环
    - dispatch() fire-and-forget，flush() 等待全部完成
    """

    def __init__(self, hooks: list[BaseHook] | None = None) -> None:
        self._hooks: list[BaseHook] = list(hooks) if hooks else []
        self._pending: set[asyncio.Task] = set()

    # ── 管理 ────────────────────────────────────────────

    def add_hook(self, hook: BaseHook) -> None:
        self._hooks.append(hook)

    def remove_hook(self, hook: BaseHook) -> None:
        try:
            self._hooks.remove(hook)
        except ValueError:
            pass

    @property
    def hooks(self) -> list[BaseHook]:
        return list(self._hooks)

    # ── 分发 ────────────────────────────────────────────

    async def dispatch(self, method: str, **kwargs: Any) -> None:
        if not self._hooks:
            return

        async def _safe_call(hook: BaseHook) -> None:
            try:
                fn = getattr(hook, method, None)
                if fn is None:
                    logger.warning(
                        "Hook %s has no method %s", type(hook).__name__, method
                    )
                    return
                await fn(**kwargs)
            except Exception:
                logger.exception("Hook %s.%s failed", type(hook).__name__, method)

        for hook in self._hooks:
            task = asyncio.create_task(_safe_call(hook))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)

    async def flush(self) -> None:
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)

    # ── 便捷方法 ────────────────────────────────────────

    async def on_message_start(self, **kwargs: Any) -> None:
        await self.dispatch("on_message_start", **kwargs)

    async def on_chunk_delta(self, **kwargs: Any) -> None:
        await self.dispatch("on_chunk_delta", **kwargs)

    async def on_chunk_complete(self, **kwargs: Any) -> None:
        await self.dispatch("on_chunk_complete", **kwargs)

    async def on_message_finish(self, **kwargs: Any) -> None:
        await self.dispatch("on_message_finish", **kwargs)

    async def on_message_error(self, **kwargs: Any) -> None:
        await self.dispatch("on_message_error", **kwargs)

    async def on_turn_start(self, **kwargs: Any) -> None:
        await self.dispatch("on_turn_start", **kwargs)

    async def on_turn_end(self, **kwargs: Any) -> None:
        await self.dispatch("on_turn_end", **kwargs)

    async def on_subagent_start(self, **kwargs: Any) -> None:
        await self.dispatch("on_subagent_start", **kwargs)

    async def on_subagent_end(self, **kwargs: Any) -> None:
        await self.dispatch("on_subagent_end", **kwargs)
