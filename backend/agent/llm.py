import asyncio
import os
import time
from typing import Any, AsyncIterator, Dict, List

from openai import AsyncOpenAI

from agent.metrics import (
    LLMCallContext,
    SQLiteLLMMetricsStore,
    usage_to_dict,
    utc_now_iso,
)
from agent.utils._term import dim, error, info, success


class HelloAgentsLLM:
    """OpenAI-compatible async LLM client with native tool calling."""

    def __init__(
        self,
        model: str | None = None,
        apiKey: str | None = None,
        baseUrl: str | None = None,
        timeout: int | None = None,
        metrics_store: SQLiteLLMMetricsStore | None = None,
    ):
        model = model or os.getenv("LLM_MODEL_ID")
        apiKey = apiKey or os.getenv("LLM_API_KEY")
        baseUrl = baseUrl or os.getenv("LLM_BASE_URL")
        timeout = timeout or int(os.getenv("LLM_TIMEOUT", 60))

        if not all([model, apiKey, baseUrl]):
            raise ValueError("模型ID、API密钥和服务地址必须被提供或在.env文件中定义。")

        self.model = model
        self.metrics_store = metrics_store
        self._thinking_enabled = os.getenv("LLM_THINKING_ENABLED", "").lower() in (
            "1",
            "true",
            "yes",
        )
        self._stream_usage_enabled = os.getenv(
            "LLM_STREAM_USAGE_ENABLED", "1"
        ).lower() not in ("0", "false", "no")
        self.client = AsyncOpenAI(api_key=apiKey, base_url=baseUrl, timeout=timeout)

    async def think_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0,
        tools: List[dict] | None = None,
        metrics_context: LLMCallContext | None = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """流式调用 LLM，yield 分类事件。

        Yields:
            {"kind": "reasoning",       "token": "..."}
            {"kind": "content",         "token": "..."}
            {"kind": "tool_call_chunk", "tool_call": {...}}
            {"kind": "finish_reason",   "finish_reason": "stop"|"tool_calls"}
        """

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
        if self._stream_usage_enabled:
            kwargs["stream_options"] = {"include_usage": True}
        if self._thinking_enabled:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            kwargs["reasoning_effort"] = "max"

        created_at = utc_now_iso()
        started_at = time.perf_counter()
        usage: dict[str, Any] | None = None
        finish_reason: str | None = None
        error_message: str | None = None

        try:
            response = await self.client.chat.completions.create(**kwargs)
            async for chunk in response:
                chunk_usage = usage_to_dict(getattr(chunk, "usage", None))
                if chunk_usage is not None:
                    usage = chunk_usage

                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                # reasoning
                reasoning = getattr(delta, "reasoning_content", None) or ""
                if reasoning:
                    yield {"kind": "reasoning", "token": reasoning}

                # content
                content = delta.content or ""
                if content:
                    yield {"kind": "content", "token": content}

                # tool_calls
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        yield {
                            "kind": "tool_call_chunk",
                            "tool_call": {
                                "index": tc.index,
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name if tc.function else "",
                                    "arguments": (
                                        tc.function.arguments if tc.function else ""
                                    ),
                                },
                            },
                        }

                # finish_reason
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                    yield {
                        "kind": "finish_reason",
                        "finish_reason": choice.finish_reason,
                    }

        except asyncio.CancelledError:
            error_message = "cancelled"
            raise
        except Exception as e:
            error_message = str(e)
            yield {"kind": "content", "token": f"\n[Error: {e}]"}
        finally:
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            if self.metrics_store is not None:
                try:
                    self.metrics_store.record_call(
                        model=self.model,
                        created_at=created_at,
                        latency_ms=latency_ms,
                        context=metrics_context,
                        finish_reason=finish_reason,
                        usage=usage,
                        error=error_message,
                    )
                except Exception as exc:
                    print(error(f"Failed to record LLM metrics: {exc}"))
