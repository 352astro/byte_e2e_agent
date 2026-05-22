import os
from typing import Any, AsyncIterator, Dict, List

from openai import AsyncOpenAI

from agent.utils._term import dim, error, info, success


class HelloAgentsLLM:
    """OpenAI-compatible async LLM client with native tool calling."""

    def __init__(
        self,
        model: str | None = None,
        apiKey: str | None = None,
        baseUrl: str | None = None,
        timeout: int | None = None,
    ):
        model = model or os.getenv("LLM_MODEL_ID")
        apiKey = apiKey or os.getenv("LLM_API_KEY")
        baseUrl = baseUrl or os.getenv("LLM_BASE_URL")
        timeout = timeout or int(os.getenv("LLM_TIMEOUT", 60))

        if not all([model, apiKey, baseUrl]):
            raise ValueError("模型ID、API密钥和服务地址必须被提供或在.env文件中定义。")

        self.model = model
        self._thinking_enabled = os.getenv("LLM_THINKING_ENABLED", "").lower() in (
            "1",
            "true",
            "yes",
        )
        self.client = AsyncOpenAI(api_key=apiKey, base_url=baseUrl, timeout=timeout)

    async def think_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0,
        tools: List[dict] | None = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """流式调用 LLM，yield 分类事件。

        Yields:
            {"kind": "reasoning",       "token": "..."}
            {"kind": "content",         "token": "..."}
            {"kind": "tool_call_chunk", "tool_call": {...}}
            {"kind": "finish_reason",   "finish_reason": "stop"|"tool_calls"}
        """
        print(info(f"Calling {self.model} ..."))

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
        if self._thinking_enabled:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            kwargs["reasoning_effort"] = "high"

        try:
            response = await self.client.chat.completions.create(**kwargs)
            async for chunk in response:
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
                    yield {
                        "kind": "finish_reason",
                        "finish_reason": choice.finish_reason,
                    }

        except Exception as e:
            yield {"kind": "content", "token": f"\n[Error: {e}]"}

    async def think(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0,
        tools: List[dict] | None = None,
    ) -> str | None:
        """CLI 用——完整响应 + 终端打印。"""
        print(success("Response:"))
        collected: list[str] = []
        has_reasoning = False

        try:
            async for event in self.think_stream(messages, temperature, tools):
                token = event.get("token", "")
                if event["kind"] == "reasoning":
                    if not has_reasoning:
                        print(dim("  [Deep Think]"))
                        has_reasoning = True
                    print(dim(token), end="", flush=True)
                elif event["kind"] == "content":
                    if has_reasoning and not collected:
                        print()
                    print(token, end="", flush=True)
                    collected.append(token)
                elif event["kind"] == "tool_call_chunk":
                    tc = event["tool_call"]
                    if tc["function"]["name"]:
                        print(f"\n{tool('[Tool]')} {tc['function']['name']}", end="")
                elif event["kind"] == "finish_reason":
                    print()
        except Exception:
            pass

        print()
        full = "".join(collected)
        return full if full.strip() else None
