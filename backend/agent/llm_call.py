"""LLM streaming call with retry and interrupt support.

Pure openai implementation. Stateless, all dependencies explicit.
"""

from __future__ import annotations

import asyncio
import time
import uuid as _uuid

from openai import APIConnectionError, APIStatusError, APITimeoutError

from agent.errors import InterruptedError
from shared.hooks import HookManager
from shared.types import Message, ToolCall

_SUBAGENT_DEBUG = True  # Set False to suppress subagent console debug output
_STREAM_END = object()


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _next_stream_chunk(iterator):
    try:
        return next(iterator)
    except StopIteration:
        return _STREAM_END


async def _next_stream_chunk_async(iterator, *, threaded: bool):
    if not threaded:
        return _next_stream_chunk(iterator)
    return await asyncio.to_thread(_next_stream_chunk, iterator)


def _model_retry_delay_ms(attempt: int) -> int:
    from app.core.config import get_settings

    s = get_settings()
    base_ms = max(0, s.llm_retry_base_delay_ms)
    max_ms = max(base_ms, s.llm_retry_max_delay_ms)
    return min(max_ms, base_ms * (2**attempt))


def _model_request_client(client):
    with_options = getattr(type(client), "with_options", None)
    if not callable(with_options):
        return client
    try:
        return client.with_options(max_retries=0)
    except TypeError:
        return client


def _is_mock_client(client) -> bool:
    return type(client).__module__.startswith("unittest.mock")


async def _create_model_stream(client, kwargs: dict):
    create = client.chat.completions.create
    if _is_mock_client(client):
        return create(**kwargs)
    return await asyncio.to_thread(create, **kwargs)


def _is_retriable_model_error(exc: Exception) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    if isinstance(exc, APIStatusError):
        status_code = getattr(exc, "status_code", 0) or 0
        return status_code in (408, 409, 429) or status_code >= 500
    return False


def _model_error_detail(exc: Exception) -> str:
    if isinstance(exc, APITimeoutError):
        return "Timeout"
    if isinstance(exc, APIConnectionError):
        return "Connection error"
    if isinstance(exc, APIStatusError):
        status_code = getattr(exc, "status_code", 0) or 0
        return f"HTTP {status_code}" if status_code else "API status error"
    return type(exc).__name__


async def _sleep_or_interrupt(delay: float, interrupt_event: asyncio.Event) -> None:
    try:
        await asyncio.wait_for(interrupt_event.wait(), timeout=delay)
    except TimeoutError:
        return
    raise InterruptedError("Interrupted during model retry backoff")


async def _debug_bridge_silent(msg: Message | None, label: str) -> None:
    """Subagent debug output (simplified)."""
    if not _SUBAGENT_DEBUG or msg is None:
        return
    if msg.content:
        print(msg.content, end="", flush=True)
    if msg.tool_calls:
        for tc in msg.tool_calls:
            print(f"\n[{label}] 🔧 {tc.function.name}")


# ═══════════════════════════════════════════════════════════
# model_call
# ═══════════════════════════════════════════════════════════


async def model_call(
    client,  # openai.OpenAI
    model_id: str,
    session_id: str,
    messages: list[dict],
    tools: list[dict],
    message_id: str,
    *,
    turn_id: str = "",
    interrupt_event: asyncio.Event,
    hook_manager: HookManager | None = None,
    streaming_holder: list[Message | None] | None = None,
) -> tuple[Message, str | None]:
    """Streaming LLM call (native openai).  Builds Message + dispatches hooks.

    If *streaming_holder* is provided (single-element list), its element is
    updated in-place to the current Message during streaming.  Callers can read
    this reference for partially-built messages (e.g. /recover endpoint).

    Returns ``(msg, finish_reason)``.
    """
    finish_reason: str | None = None

    # ── Create Message ──────────────────────────────
    msg = Message.assistant_message(message_id, turn_id or message_id)
    if streaming_holder is not None:
        streaming_holder[0] = msg
    if hook_manager is not None:
        await hook_manager.on_message_start(msg=msg, session_id=session_id)

    kwargs: dict = {
        "model": model_id,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "reasoning_effort": "high",
        "extra_body": {"thinking": {"type": "enabled"}},
    }
    if tools:
        kwargs["tools"] = tools

    request_client = _model_request_client(client)
    from app.core.config import get_settings

    max_retries = max(0, get_settings().llm_max_retries)
    max_attempts = max_retries + 1
    retry_notice_id = f"model-retry:{session_id}:{turn_id or message_id}"

    for attempt in range(max_attempts):
        received_chunk = False
        try:
            stream = await _create_model_stream(request_client, kwargs)
            threaded_stream = not isinstance(stream, (list, tuple))
            stream_iter = iter(stream)

            while True:
                chunk = await _next_stream_chunk_async(
                    stream_iter,
                    threaded=threaded_stream,
                )
                if chunk is _STREAM_END:
                    break
                if interrupt_event.is_set():
                    raise InterruptedError("Interrupted during LLM call")

                received_chunk = True
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                _content = getattr(delta, "content", None) or ""
                _reasoning = getattr(delta, "reasoning_content", None) or ""
                _tool_calls = getattr(delta, "tool_calls", None) or []
                _finish = getattr(chunk.choices[0], "finish_reason", None) or ""
                _usage = getattr(chunk, "usage", None)

                # ── reasoning ────────────────────────────────
                if _reasoning:
                    msg.reasoning += _reasoning
                    if hook_manager is not None:
                        await hook_manager.on_chunk_delta(
                            msg=msg,
                            field="reasoning",
                            delta=_reasoning,
                            session_id=session_id,
                        )

                # ── text content ─────────────────────────────
                if _content:
                    msg.content += _content
                    if hook_manager is not None:
                        await hook_manager.on_chunk_delta(
                            msg=msg,
                            field="content",
                            delta=_content,
                            session_id=session_id,
                        )

                # ── tool calls ───────────────────────────────
                for tc in _tool_calls:
                    idx = getattr(tc, "index", 0)
                    tc_id = getattr(tc, "id", None) or ""
                    tc_fn = getattr(tc, "function", None)
                    tc_name = getattr(tc_fn, "name", None) or "" if tc_fn else ""
                    tc_args = getattr(tc_fn, "arguments", None) or "" if tc_fn else ""

                    while len(msg.tool_calls) <= idx:
                        msg.tool_calls.append(ToolCall())
                    if tc_id:
                        msg.tool_calls[idx].id = tc_id

                    if tc_name:
                        msg.tool_calls[idx].function.name += tc_name
                        if hook_manager is not None:
                            await hook_manager.on_chunk_delta(
                                msg=msg,
                                field="tool_calls",
                                delta=tc_name,
                                tool_name=msg.tool_calls[idx].function.name,
                                tool_index=idx,
                                sub_field="name",
                                session_id=session_id,
                            )

                    if tc_args:
                        msg.tool_calls[idx].function.arguments += tc_args
                        if hook_manager is not None:
                            await hook_manager.on_chunk_delta(
                                msg=msg,
                                field="tool_calls",
                                delta=tc_args,
                                tool_name=msg.tool_calls[idx].function.name,
                                tool_index=idx,
                                sub_field="args",
                                session_id=session_id,
                            )

                if _finish:
                    finish_reason = _finish

                if _usage and not hasattr(msg, "_usage"):
                    if hasattr(_usage, "model_dump"):
                        object.__setattr__(msg, "_usage", _usage.model_dump())
                    elif hasattr(_usage, "prompt_tokens"):
                        object.__setattr__(
                            msg,
                            "_usage",
                            {
                                "prompt_tokens": getattr(_usage, "prompt_tokens", 0),
                                "completion_tokens": getattr(_usage, "completion_tokens", 0),
                                "total_tokens": getattr(_usage, "total_tokens", 0),
                            },
                        )
                    else:
                        object.__setattr__(msg, "_usage", _usage)
            if hook_manager is not None and attempt > 0:
                await hook_manager.on_runtime_notice(
                    notice_id=retry_notice_id,
                    level="success",
                    title="Model request recovered",
                    detail="Streaming resumed.",
                    ttl_ms=1800,
                    session_id=session_id,
                    turn_id=turn_id,
                    message_id=message_id,
                )
            break
        except InterruptedError:
            raise
        except Exception as exc:
            should_retry = (
                not received_chunk and attempt < max_retries and _is_retriable_model_error(exc)
            )
            if not should_retry:
                raise
            retry_index = attempt + 1
            delay_ms = _model_retry_delay_ms(attempt)
            retry_at = int(time.time() * 1000) + delay_ms
            if hook_manager is not None:
                await hook_manager.on_runtime_notice(
                    notice_id=retry_notice_id,
                    level="warn",
                    title="Model request retrying",
                    detail=_model_error_detail(exc),
                    progress=f"{retry_index}/{max_retries}",
                    retry_after_ms=delay_ms,
                    retry_at=retry_at,
                    ttl_ms=5000,
                    session_id=session_id,
                    turn_id=turn_id,
                    message_id=message_id,
                )
            delay = delay_ms / 1000.0
            await _sleep_or_interrupt(delay, interrupt_event)

    # ── Complete ──────────────────────────────────────
    msg.mark_complete()
    if streaming_holder is not None:
        streaming_holder[0] = None
    if hook_manager is not None:
        usage = getattr(msg, "_usage", None) or {}
        await hook_manager.on_message_finish(
            msg=msg,
            finish_reason=finish_reason or "stop",
            usage=usage,
            session_id=session_id,
        )

    return msg, finish_reason
