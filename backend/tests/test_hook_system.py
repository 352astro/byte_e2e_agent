"""链路 2: Hook 体系 — BaseHook + HookManager + 三个内置 Hook。

测试范围:
- BaseHook 所有方法默认 no-op
- HookManager add/remove/dispatch/flush
- dispatch 并行 + 单 hook 异常隔离
- StreamDriverHook SSE 事件序列
- MetricsHook 计时 + record_call
- LoggingHook verbose 控制
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from agent.hook.logging_hook import LoggingHook
from agent.hook.metrics_hook import MetricsHook
from agent.hook.shadow_commit_hook import ShadowCommitHook
from agent.hook.stream_hook import StreamDriverHook
from shared.hooks import BaseHook, HookManager
from shared.types import Message, StreamEvent, StreamEventKind

# ═══════════════════════════════════════════════════════════
# BaseHook
# ═══════════════════════════════════════════════════════════


class TestBaseHook:
    def test_all_methods_are_noop(self):
        """BaseHook 所有方法默认 no-op，不抛异常。"""
        hook = BaseHook()
        # 所有方法应该都是可调用的且不抛异常
        for name in dir(BaseHook):
            if name.startswith("on_"):
                assert callable(getattr(hook, name)), f"{name} should be callable"


# ═══════════════════════════════════════════════════════════
# HookManager
# ═══════════════════════════════════════════════════════════


class TestHookManager:
    def test_empty_manager_dispatch_noop(self):
        """空的 HookManager dispatch 不抛异常。"""
        mgr = HookManager()
        # 同步调度不应抛异常
        assert len(mgr.hooks) == 0

    @pytest.mark.asyncio
    async def test_add_remove_hooks(self):
        """add_hook / remove_hook 正确增删。"""
        h1 = BaseHook()
        h2 = BaseHook()
        mgr = HookManager([h1])
        assert len(mgr.hooks) == 1

        mgr.add_hook(h2)
        assert len(mgr.hooks) == 2
        assert mgr.hooks == [h1, h2]  # 顺序保持

        mgr.remove_hook(h1)
        assert len(mgr.hooks) == 1
        assert mgr.hooks == [h2]

        # 移除不存在的 hook 不抛异常
        mgr.remove_hook(h1)

    @pytest.mark.asyncio
    async def test_dispatch_calls_all_hooks(self):
        """dispatch 并行调用所有注册的 hook。"""
        called: set[str] = set()

        class TrackHook(BaseHook):
            async def on_turn_start(self, **kwargs):
                called.add(kwargs["turn_id"])

        h1 = TrackHook()
        h2 = TrackHook()
        mgr = HookManager([h1, h2])
        await mgr.dispatch("on_turn_start", turn_id="t1", session_id="s1")
        # fire-and-forget, need flush
        await mgr.flush()
        assert called == {"t1"}

    @pytest.mark.asyncio
    async def test_dispatch_isolates_errors(self):
        """单个 hook 抛异常不影响其他 hook 和主循环。"""
        called_ok = False

        class BadHook(BaseHook):
            async def on_turn_start(self, **kwargs):
                raise RuntimeError("boom")

        class GoodHook(BaseHook):
            async def on_turn_start(self, **kwargs):
                nonlocal called_ok
                called_ok = True

        mgr = HookManager([BadHook(), GoodHook()])
        # dispatch 不抛异常
        await mgr.dispatch("on_turn_start", turn_id="t1", session_id="s1")
        await mgr.flush()
        assert called_ok, "GoodHook should have been called despite BadHook error"

    @pytest.mark.asyncio
    async def test_flush_waits_all_pending(self):
        """flush 等待所有 pending task 完成。"""
        results: list[str] = []

        class SlowHook(BaseHook):
            async def on_turn_start(self, **kwargs):
                await asyncio.sleep(0.05)
                results.append("slow")

        class FastHook(BaseHook):
            async def on_turn_start(self, **kwargs):
                results.append("fast")

        mgr = HookManager([SlowHook(), FastHook()])
        await mgr.dispatch("on_turn_start", turn_id="t", session_id="s")
        # 不 flush 时可能还没完成
        await mgr.flush()
        assert "fast" in results
        assert "slow" in results

    @pytest.mark.asyncio
    async def test_convenience_methods(self):
        """便捷方法 (on_message_start 等) 正确委托给 dispatch。"""
        called = False

        class SpyHook(BaseHook):
            async def on_message_start(self, *, msg: Message, **kwargs):
                nonlocal called
                called = True

        mgr = HookManager([SpyHook()])
        msg = Message(id="m", turn_id="t")
        await mgr.on_message_start(msg=msg, model_id="gpt-4")
        await mgr.flush()
        assert called

    @pytest.mark.asyncio
    async def test_hooks_property_returns_copy(self):
        """hooks 属性返回副本，修改不影响内部。"""
        mgr = HookManager([BaseHook()])
        hooks = mgr.hooks
        hooks.append(BaseHook())
        assert len(mgr.hooks) == 1  # 原列表不变


# ═══════════════════════════════════════════════════════════
# StreamDriverHook
# ═══════════════════════════════════════════════════════════


class TestStreamDriverHook:
    def test_subscribe_unsubscribe(self):
        """订阅和取消订阅。"""
        driver = StreamDriverHook()
        q = driver.subscribe()
        assert isinstance(q, asyncio.Queue)

        driver.unsubscribe(q)
        # 再次取消不报错
        driver.unsubscribe(q)

    @pytest.mark.asyncio
    async def test_close_sends_none(self):
        """close 向所有订阅者发送 None。"""
        driver = StreamDriverHook()
        q = driver.subscribe()
        driver.close()
        ev = await q.get()
        assert ev is None

    @pytest.mark.asyncio
    async def test_subscribe_after_close_gets_none_immediately(self):
        """close 后再订阅立刻收到 None。"""
        driver = StreamDriverHook()
        driver.close()
        q = driver.subscribe()
        ev = q.get_nowait()
        assert ev is None

    @pytest.mark.asyncio
    async def test_on_message_start_broadcasts_message_start(self):
        """on_message_start → MESSAGE_START StreamEvent。"""
        driver = StreamDriverHook()
        q = driver.subscribe()
        msg = Message(id="m1", turn_id="t1")
        await driver.on_message_start(msg=msg)
        ev = q.get_nowait()
        assert ev.kind == StreamEventKind.MESSAGE_START
        assert ev.message_id == "m1"
        assert ev.turn_id == "t1"

    @pytest.mark.asyncio
    async def test_on_chunk_delta_skips_empty(self):
        """空的 delta 或 message_id 不广播。"""
        driver = StreamDriverHook()
        q = driver.subscribe()
        msg_empty = Message(id="", turn_id="t1")
        msg_ok = Message(id="m1", turn_id="t1")
        await driver.on_chunk_delta(msg=msg_ok, field="content", delta="")
        await driver.on_chunk_delta(msg=msg_empty, field="content", delta="x")
        assert q.empty()

    @pytest.mark.asyncio
    async def test_on_chunk_delta_broadcasts_chunk_delta(self):
        """on_chunk_delta → CHUNK_DELTA。"""
        driver = StreamDriverHook()
        q = driver.subscribe()
        msg = Message(id="m1", turn_id="t1")
        await driver.on_chunk_delta(
            msg=msg,
            field="content",
            delta="hello",
        )
        ev = q.get_nowait()
        assert ev.kind == StreamEventKind.CHUNK_DELTA
        assert ev.delta == "hello"
        assert ev.field == "content"

    @pytest.mark.asyncio
    async def test_on_chunk_delta_skips_empty_delta(self):
        """空 delta 不广播。"""
        driver = StreamDriverHook()
        q = driver.subscribe()
        msg = Message(id="m1", turn_id="t1")
        await driver.on_chunk_delta(msg=msg, field="content", delta="")
        assert q.empty()

    @pytest.mark.asyncio
    async def test_on_chunk_delta_with_tool_name(self):
        """TOOL_CALL chunk 带 tool_name。"""
        driver = StreamDriverHook()
        q = driver.subscribe()
        msg = Message(id="m1", turn_id="t1")
        await driver.on_chunk_delta(
            msg=msg,
            field="tool_calls",
            delta='{"cmd":"ls"}',
            tool_name="Shell",
        )
        ev = q.get_nowait()
        assert ev.tool_name == "Shell"

    @pytest.mark.asyncio
    async def test_on_message_finish_broadcasts_message_finish(self):
        """on_message_finish → MESSAGE_FINISH。"""
        driver = StreamDriverHook()
        q = driver.subscribe()
        msg = Message(id="m1", turn_id="t1")
        await driver.on_message_finish(msg=msg)
        ev = q.get_nowait()
        assert ev.kind == StreamEventKind.MESSAGE_FINISH
        assert ev.message_id == "m1"

    @pytest.mark.asyncio
    async def test_on_chunk_complete_tool_call(self):
        """on_chunk_complete(field=tool_calls) → CHUNK_COMPLETE。"""
        driver = StreamDriverHook()
        q = driver.subscribe()
        msg = Message(id="tc1", turn_id="t1")
        await driver.on_chunk_complete(
            msg=msg,
            field="tool_calls",
            full_content='{"command": "echo hello"}',
            tool_name="Shell",
            tool_args='{"command": "echo hello"}',
        )
        ev = q.get_nowait()
        assert ev.kind == StreamEventKind.CHUNK_COMPLETE
        assert ev.field == "tool_calls"
        assert ev.tool_name == "Shell"

    @pytest.mark.asyncio
    async def test_on_chunk_complete_tool_result(self):
        """on_chunk_complete(field=tool_result) → CHUNK_COMPLETE。"""
        driver = StreamDriverHook()
        q = driver.subscribe()
        msg = Message(id="tc1", turn_id="t1")
        await driver.on_chunk_complete(
            msg=msg,
            field="tool_result",
            full_content="hello world",
            tool_name="Shell",
            is_error=False,
        )
        ev = q.get_nowait()
        assert ev.kind == StreamEventKind.CHUNK_COMPLETE
        assert ev.field == "tool_result"
        assert ev.full_content == "hello world"

    @pytest.mark.asyncio
    async def test_on_turn_end_broadcasts_turn_complete(self):
        """on_turn_end → TURN_COMPLETE。"""
        driver = StreamDriverHook()
        q = driver.subscribe()
        await driver.on_turn_end(turn_id="t1", input_tokens=100, output_tokens=50)
        ev = q.get_nowait()
        assert ev.kind == StreamEventKind.TURN_COMPLETE
        assert ev.input_tokens == 100
        assert ev.output_tokens == 50

    @pytest.mark.asyncio
    async def test_on_message_error_broadcasts_interrupted(self):
        """on_message_error → INTERRUPTED。"""
        driver = StreamDriverHook()
        q = driver.subscribe()
        msg = Message(id="m1", turn_id="t1")
        await driver.on_message_error(msg=msg, error=RuntimeError("boom"))
        ev = q.get_nowait()
        assert ev.kind == StreamEventKind.INTERRUPTED
        assert "boom" in ev.reason

    @pytest.mark.asyncio
    async def test_multiple_subscribers_all_receive(self):
        """多个订阅者都收到事件。"""
        driver = StreamDriverHook()
        q1 = driver.subscribe()
        q2 = driver.subscribe()

        msg = Message(id="m1", turn_id="t1")
        await driver.on_message_finish(msg=msg)

        for q in [q1, q2]:
            ev = q.get_nowait()
            assert ev.kind == StreamEventKind.MESSAGE_FINISH

    @pytest.mark.asyncio
    async def test_dead_subscriber_removed(self):
        """队列满的订阅者被自动移除。"""
        driver = StreamDriverHook()
        # 创建一个 maxsize=1 的队列，先塞满
        q = asyncio.Queue(maxsize=1)
        # 手动加入 subscriber 列表（绕过 subscribe）
        driver._subscribers.append(q)
        q.put_nowait(StreamEvent.message_start("t", "m"))  # 填满

        msg = Message(id="m1", turn_id="t1")
        await driver.on_message_finish(msg=msg)
        # q 被标记为 dead 并移除
        assert q not in driver._subscribers


# ═══════════════════════════════════════════════════════════
# MetricsHook
# ═══════════════════════════════════════════════════════════


class TestMetricsHook:
    @pytest.mark.asyncio
    async def test_on_message_start_records_time(self):
        """on_message_start 记录开始时间。"""
        store = MagicMock()
        hook = MetricsHook(store, model_id="gpt-4")
        msg = Message(id="m1", turn_id="t1")
        await hook.on_message_start(msg=msg)
        assert "m1" in hook._start_times

    @pytest.mark.asyncio
    async def test_on_message_finish_calls_record(self):
        """on_message_finish 调用 store.record_call。"""
        store = MagicMock()
        hook = MetricsHook(store, model_id="gpt-4")
        msg = Message(id="m1", turn_id="t1")
        await hook.on_message_start(msg=msg)
        await hook.on_message_finish(
            msg=msg,
            finish_reason="stop",
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            model_id="gpt-4",
        )
        # record_call 应该被调用
        assert store.record_call.called

    @pytest.mark.asyncio
    async def test_on_message_finish_clears_start_time(self):
        """on_message_finish 后清除对应 message_id 的开始时间。"""
        store = MagicMock()
        hook = MetricsHook(store)
        msg = Message(id="m1", turn_id="t")
        await hook.on_message_start(msg=msg)
        await hook.on_message_finish(msg=msg, finish_reason="stop", usage={})
        assert "m1" not in hook._start_times

    @pytest.mark.asyncio
    async def test_on_message_error_records_error(self):
        """on_message_error 也调用 record_call 并记录错误。"""
        store = MagicMock()
        hook = MetricsHook(store, model_id="gpt-4")
        msg = Message(id="m1", turn_id="t1")
        await hook.on_message_start(msg=msg)
        await hook.on_message_error(
            msg=msg,
            error=RuntimeError("timeout"),
        )
        assert store.record_call.called

    @pytest.mark.asyncio
    async def test_latency_falls_back_to_explicit(self):
        """显式传入 latency_ms 覆盖计时。"""
        store = MagicMock()
        hook = MetricsHook(store, model_id="gpt-4")
        msg = Message(id="m1", turn_id="t1")
        await hook.on_message_finish(
            msg=msg,
            finish_reason="stop",
            usage={},
            latency_ms=1234,
        )
        call_args = store.record_call.call_args
        assert call_args.kwargs["latency_ms"] == 1234

    @pytest.mark.asyncio
    async def test_record_call_exception_does_not_propagate(self):
        """store.record_call 异常不向上传播。"""
        store = MagicMock()
        store.record_call.side_effect = RuntimeError("db error")
        hook = MetricsHook(store)
        msg = Message(id="m1", turn_id="t1")
        # 不应抛异常
        await hook.on_message_finish(msg=msg, finish_reason="stop", usage={})


# ═══════════════════════════════════════════════════════════
# ShadowCommitHook
# ═══════════════════════════════════════════════════════════


class TestShadowCommitHook:
    @pytest.mark.asyncio
    async def test_on_turn_start_creates_initial_commit_once(self):
        repo = MagicMock()
        repo.list_commits.return_value = []
        hook = ShadowCommitHook(repo)

        await hook.on_turn_start(session_id="s1")

        repo.snapshot.assert_called_once_with("s1", "Initial workspace state")

    @pytest.mark.asyncio
    async def test_on_message_finish_snapshots_user_message_content(self):
        repo = MagicMock()
        repo.list_commits.return_value = ["existing"]
        hook = ShadowCommitHook(repo)
        msg = Message.user_message("m1", "t1", "hello\nmore detail")

        await hook.on_message_finish(msg=msg, session_id="s1")

        repo.snapshot.assert_called_once_with("s1", "hello")

    @pytest.mark.asyncio
    async def test_on_message_finish_ignores_assistant_message(self):
        repo = MagicMock()
        hook = ShadowCommitHook(repo)
        msg = Message.assistant_message("m1", "t1")

        await hook.on_message_finish(msg=msg, session_id="s1")

        repo.snapshot.assert_not_called()


# ═══════════════════════════════════════════════════════════
# LoggingHook
# ═══════════════════════════════════════════════════════════


class TestLoggingHook:
    def test_verbose_false_suppresses_output(self, capsys):
        """verbose=False 时不输出任何内容。"""
        import asyncio

        async def _run():
            hook = LoggingHook(verbose=False)
            msg = Message(id="m1", turn_id="t1")
            await hook.on_message_start(msg=msg, model_id="gpt-4")
            await hook.on_chunk_delta(msg=msg, field="content", delta="hello")
            await hook.on_message_finish(msg=msg, finish_reason="stop", usage={}, latency_ms=0)
            await hook.on_turn_start(user_question="test")

        asyncio.run(_run())
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_verbose_true_outputs(self, capsys):
        """verbose=True 时有输出。"""
        import asyncio

        async def _run():
            hook = LoggingHook(verbose=True)
            await hook.on_turn_start(turn_id="t1", session_id="s1", user_question="hello world")

        asyncio.run(_run())
        captured = capsys.readouterr()
        assert "hello world" in captured.out

    def test_step_counter_resets_on_turn_start(self):
        """on_turn_start 重置 step 计数器。"""
        hook = LoggingHook(verbose=True)
        hook._step = 5
        import asyncio

        async def _run():
            await hook.on_turn_start(turn_id="t", session_id="s", user_question="q")

        asyncio.run(_run())
        assert hook._step == 0

    def test_step_counter_increments_on_message_start(self):
        """on_message_start 递增 step。"""
        hook = LoggingHook(verbose=True)
        import asyncio

        async def _run():
            msg = Message(id="m1", turn_id="t1")
            await hook.on_message_start(msg=msg)

        asyncio.run(_run())
        assert hook._step == 1
