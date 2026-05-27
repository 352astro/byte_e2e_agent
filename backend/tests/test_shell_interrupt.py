"""Shell 超时 / 中断边界测试。

测试 PersistentTerminal 在极端条件下的中断能力和恢复能力。
所有 timeout 控制在 1s 以内，使用本机 sleep / echo 等基础命令。
"""

from __future__ import annotations

import asyncio

import pytest

from agent.sandbox import Sandbox

# ── helpers ────────────────────────────────────────────


async def _collect_stream(
    sb: Sandbox,
    command: str,
    timeout_ms: int = 800,
    interrupt_event: asyncio.Event | None = None,
) -> str:
    """流式执行并收集完整输出。"""
    parts: list[str] = []
    async for chunk in sb.stream_shell(
        command,
        timeout_ms=timeout_ms,
        interrupt_event=interrupt_event or asyncio.Event(),
    ):
        parts.append(chunk)
    return "".join(parts)


async def _run(sb: Sandbox, command: str, timeout_ms: int = 800) -> str:
    """同步执行并返回结果。"""
    return await sb.run_shell(command, timeout_ms=timeout_ms)


# ── tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_normal_execution():
    """基本：正常命令输出正确，不含超时/中断提示。"""
    sb = Sandbox()
    try:
        out = await _collect_stream(sb, "echo hello", timeout_ms=500)
        assert "hello" in out
        assert "timed out" not in out.lower()
        assert "interrupted" not in out.lower()
    finally:
        await sb.shutdown()


@pytest.mark.asyncio
async def test_timeout_then_terminal_recovers():
    """超时后 stream_shell yield 超时提示，terminal 自动恢复。"""
    sb = Sandbox()
    try:
        out = await _collect_stream(sb, "sleep 3", timeout_ms=500)
        assert "timed out" in out.lower(), f"Expected timeout message, got: {out!r}"

        out2 = await _run(sb, "echo recovered", timeout_ms=500)
        assert "recovered" in out2, (
            f"Terminal should be clean after timeout, got: {out2!r}"
        )
    finally:
        await sb.shutdown()


@pytest.mark.asyncio
async def test_timeout_repeatable():
    """连续两次超时后 terminal 仍可正常执行。"""
    sb = Sandbox()
    try:
        await _collect_stream(sb, "sleep 3", timeout_ms=400)
        await _collect_stream(sb, "sleep 3", timeout_ms=400)
        out = await _run(sb, "echo survived-2-timeouts", timeout_ms=500)
        assert "survived-2-timeouts" in out, (
            f"Terminal should survive multiple timeouts, got: {out!r}"
        )
    finally:
        await sb.shutdown()


@pytest.mark.asyncio
async def test_user_interrupt():
    """用户中断：sleep 期间设置 interrupt_event，流式循环提前退出。"""
    sb = Sandbox()
    try:
        intr = asyncio.Event()
        asyncio.create_task(_delayed_set(intr, 0.2))

        parts: list[str] = []
        async for chunk in sb.stream_shell(
            "sleep 5", timeout_ms=3000, interrupt_event=intr
        ):
            parts.append(chunk)
        # 至少不崩溃
    finally:
        await sb.shutdown()


@pytest.mark.asyncio
async def test_user_interrupt_then_recover():
    """用户中断后 terminal 自动同步，后续命令正常。"""
    sb = Sandbox()
    try:
        intr = asyncio.Event()
        asyncio.create_task(_delayed_set(intr, 0.15))

        async for _ in sb.stream_shell(
            "sleep 5", timeout_ms=3000, interrupt_event=intr
        ):
            pass

        out = await _run(sb, "echo after-interrupt", timeout_ms=500)
        assert "after-interrupt" in out, (
            f"Terminal should recover after interrupt, got: {out!r}"
        )
    finally:
        await sb.shutdown()


@pytest.mark.asyncio
async def test_multiple_interrupts_with_reset_between():
    """连续多次中断，每次 reset 后仍能正常执行。"""
    sb = Sandbox()
    try:
        for i in range(3):
            intr = asyncio.Event()
            asyncio.create_task(_delayed_set(intr, 0.1))

            async for _ in sb.stream_shell(
                "sleep 5", timeout_ms=3000, interrupt_event=intr
            ):
                pass

            sb.reset_terminal()
            out = await _run(sb, f"echo survived-{i}", timeout_ms=500)
            assert f"survived-{i}" in out, f"Failed after interrupt {i}: {out!r}"
    finally:
        await sb.shutdown()


@pytest.mark.asyncio
async def test_terminal_reset_recreates_shell():
    """reset_terminal 后 terminal 是全新的，cd 状态丢失。"""
    sb = Sandbox()
    try:
        await _run(sb, "cd /tmp", timeout_ms=500)
        out = await _run(sb, "pwd", timeout_ms=500)
        assert "/tmp" in out, f"cd should work: {out!r}"

        sb.reset_terminal()

        out = await _run(sb, "pwd", timeout_ms=500)
        assert "/tmp" not in out, (
            f"After reset_terminal, should be back in workspace, got: {out!r}"
        )
    finally:
        await sb.shutdown()


@pytest.mark.asyncio
async def test_streaming_output_not_truncated():
    """流式输出完整性：多行输出应全部收到。"""
    sb = Sandbox()
    try:
        cmd = " && ".join([f"echo line{i}" for i in range(10)])
        out = await _collect_stream(sb, cmd, timeout_ms=1000)
        for i in range(10):
            assert f"line{i}" in out, f"Missing line {i} in: {out!r}"
    finally:
        await sb.shutdown()


# ── internal helper ────────────────────────────────────


async def _delayed_set(event: asyncio.Event, delay: float) -> None:
    await asyncio.sleep(delay)
    event.set()
