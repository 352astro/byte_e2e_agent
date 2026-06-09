"""Hook 基础设施 — 不属于 agent 编排逻辑，属于共享基础设施。

── 设计 ──
- BaseHook 对标 LangChain BaseCallbackHandler
- HookManager 对标 LangChain CallbackManager
- 主循环拥有数据，Hook 只收通知
- Hook 抛异常不影响主循环和其他 Hook
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from shared.types import Message

logger = logging.getLogger(__name__)


class GuardDecision(StrEnum):
    """Decision returned by guard hooks before a guarded action runs."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass
class GuardCheck:
    """A runtime action that may be allowed, denied, or require approval."""

    action_type: str
    subject: str
    payload: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    turn_id: str = ""
    message_id: str = ""
    tool_call_id: str = ""


# ═══════════════════════════════════════════════════════════
# BaseHook
# ═══════════════════════════════════════════════════════════


class BaseHook:
    """所有 Hook 的基类。每个方法默认 no-op，子类按需重写。"""

    # ── Message 生命周期 ─────────────────────────────────

    async def on_message_start(self, *, msg: Message, **kwargs: Any) -> None:
        """新 Message 开始构建。"""
        ...

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
        ...

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
        ...

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
        ...

    async def on_message_error(
        self,
        *,
        msg: Message,
        error: Exception,
        **kwargs: Any,
    ) -> None:
        """Message 构建出错。"""
        ...

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
        ...

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
        ...

    # ── SubAgent 生命周期 ────────────────────────────────

    async def on_subagent_start(
        self,
        *,
        task: str,
        parent_session_id: str,
        max_steps: int = 0,
        **kwargs: Any,
    ) -> None: ...

    async def on_subagent_end(self, *, result: str, **kwargs: Any) -> None: ...

    # ── Guard / approval ────────────────────────────────

    async def on_guard_check(
        self,
        *,
        check: GuardCheck,
        **kwargs: Any,
    ) -> GuardDecision | None:
        """Return a guard decision for an action, or None when not applicable."""
        return None

    async def on_guard_request(
        self,
        *,
        request_id: str,
        check: GuardCheck,
        **kwargs: Any,
    ) -> None:
        """Notify listeners that runtime is waiting for user approval."""
        ...

    async def on_runtime_notice(
        self,
        *,
        notice_id: str,
        level: str = "info",
        title: str = "Runtime notice",
        detail: str = "",
        progress: str = "",
        retry_after_ms: int = 0,
        retry_at: int = 0,
        ttl_ms: int = 4500,
        sticky: bool = False,
        **kwargs: Any,
    ) -> None:
        """Notify listeners about transient runtime state."""
        ...

    # ── 上下文注入 ──────────────────────────────────────

    async def on_context_assemble(
        self,
        *,
        turn_id: str,
        session_id: str,
        user_question: str,
        **kwargs: Any,
    ) -> list[dict]:
        """在 messages 构建前触发，返回需注入的额外上下文。

        每个 Hook 可返回一组 OpenAI-format dict（如 system message），
        HookManager 会合并所有 Hook 的返回值并注入到 LLM 上下文。

        典型用途：长期记忆检索、RAG、动态规则注入。
        """
        return []

    async def clear_session_state(self, *, session_id: str, **kwargs: Any) -> None:
        """Clear per-session notification state (guards, notices).

        Called at turn end / interrupt.  Hooks that hold mutable state
        (e.g. NotificationDriverHook) override this to drop stale data
        so a page refresh does not show resolved guard dialogs.
        """
        ...


# ═══════════════════════════════════════════════════════════
# HookManager
# ═══════════════════════════════════════════════════════════


class HookManager:
    """管理多个 Hook 实例，并行分发事件。

    - 每个 hook 顺序同步调用（单个 hook 异常不影响其他 hook）
    - 适合 CLI（直接 stdout）和 SSE（put_nowait 非阻塞）
    """

    def __init__(self, hooks: list[BaseHook] | None = None) -> None:
        self._hooks: list[BaseHook] = list(hooks) if hooks else []

    # ── 管理 ────────────────────────────────────────────

    def add_hook(self, hook: BaseHook) -> None:
        self._hooks.append(hook)

    def remove_hook(self, hook: BaseHook) -> None:
        with contextlib.suppress(ValueError):
            self._hooks.remove(hook)

    @property
    def hooks(self) -> list[BaseHook]:
        return list(self._hooks)

    # ── 分发 ────────────────────────────────────────────

    async def dispatch(self, method: str, **kwargs: Any) -> None:
        if not self._hooks:
            return
        for hook in self._hooks:
            try:
                fn = getattr(hook, method, None)
                if fn is None:
                    logger.warning("Hook %s has no method %s", type(hook).__name__, method)
                    continue
                await fn(**kwargs)
            except Exception:
                logger.exception("Hook %s.%s failed", type(hook).__name__, method)

    async def flush(self) -> None:
        for hook in self._hooks:
            fn = getattr(hook, "flush", None)
            if fn is None:
                continue
            try:
                await fn()
            except Exception:
                logger.exception("Hook %s.flush failed", type(hook).__name__)

    # ── 上下文收集 ────────────────────────────────────

    async def gather_context(self, **kwargs: Any) -> list[dict]:
        """收集所有 Hook 的上下文注入，合并为统一列表。

        每个 Hook.on_context_assemble() 返回一组 OpenAI-format dict，
        此方法串行调用所有 Hook 并拼接结果。单个 Hook 异常不影响其他。
        """
        result: list[dict] = []
        for hook in self._hooks:
            try:
                fn = getattr(hook, "on_context_assemble", None)
                if fn is None:
                    continue
                items = await fn(**kwargs)
                if items:
                    result.extend(items)
            except Exception:
                logger.exception("Hook %s.on_context_assemble failed", type(hook).__name__)
        return result

    async def guard_check(self, check: GuardCheck, **kwargs: Any) -> GuardDecision:
        """Collect guard decisions. Merge rule: DENY > ASK > ALLOW > None."""
        result = GuardDecision.ALLOW
        for hook in self._hooks:
            try:
                fn = getattr(hook, "on_guard_check", None)
                if fn is None:
                    continue
                decision = await fn(check=check, **kwargs)
            except Exception:
                logger.exception("Hook %s.on_guard_check failed", type(hook).__name__)
                continue
            if decision is None:
                continue
            try:
                decision = GuardDecision(decision)
            except ValueError:
                logger.warning(
                    "Hook %s returned invalid guard decision %r",
                    type(hook).__name__,
                    decision,
                )
                continue
            if decision == GuardDecision.DENY:
                return GuardDecision.DENY
            if decision == GuardDecision.ASK:
                result = GuardDecision.ASK
        return result

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

    async def on_guard_request(self, **kwargs: Any) -> None:
        await self.dispatch("on_guard_request", **kwargs)

    async def on_runtime_notice(self, **kwargs: Any) -> None:
        await self.dispatch("on_runtime_notice", **kwargs)

    async def on_context_assemble(self, **kwargs: Any) -> list[dict]:
        return await self.gather_context(**kwargs)
