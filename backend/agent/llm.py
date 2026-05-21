import os
from typing import Dict, Iterator, List

from openai import OpenAI

from agent.utils._term import dim, error, info, success


class HelloAgentsLLM:
    """
    为本书 "Hello Agents" 定制的LLM客户端。
    它用于调用任何兼容OpenAI接口的服务，并默认使用流式响应。

    支持 DeepSeek 官方思考模式（通过 LLM_THINKING_ENABLED=true 开启）：
    模型先输出 reasoning_content（思维链），再输出 content（实际回答）。
    """

    def __init__(
        self,
        model: str | None = None,
        apiKey: str | None = None,
        baseUrl: str | None = None,
        timeout: int | None = None,
    ):
        """
        初始化客户端。优先使用传入参数，如果未提供，则从环境变量加载。
        """
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

        self.client = OpenAI(api_key=apiKey, base_url=baseUrl, timeout=timeout)

    # ── 流式（供 SSE / Web UI 使用）─────────────────────

    def think_stream(
        self, messages: List[Dict[str, str]], temperature: float = 0
    ) -> Iterator[Dict[str, str]]:
        """
        流式调用 LLM，逐个 yield 带分类的 token dict。

        Yields:
            {"kind": "reasoning", "token": "..."}   — DeepSeek 思维链
            {"kind": "content",   "token": "..."}   — 模型实际输出

        不 print 任何内容，由调用方决定如何消费。
        """
        print(info(f"Calling {self.model} ..."))

        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }

        if self._thinking_enabled:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            kwargs["reasoning_effort"] = "high"

        try:
            response = self.client.chat.completions.create(**kwargs)
            for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                # DeepSeek 官方思维链（仅思考模式开启时有值）
                reasoning = getattr(delta, "reasoning_content", None) or ""
                if reasoning:
                    yield {"kind": "reasoning", "token": reasoning}

                # 模型实际输出（我们的 JSON）
                content = delta.content or ""
                if content:
                    yield {"kind": "content", "token": content}

        except Exception as e:
            yield {"kind": "content", "token": f"\n[Error: {e}]"}

    # ── 批量（供 CLI 使用）───────────────────────────────

    def think(
        self, messages: List[Dict[str, str]], temperature: float = 0
    ) -> str | None:
        """
        调用大语言模型进行思考，并返回其完整响应（仅 content 部分）。
        内部委托给 think_stream()，同时 print 到终端。
        reasoning 部分以暗色打印，content 部分正常打印。
        """
        print(success("Response:"))
        collected_content: list[str] = []
        has_reasoning = False

        try:
            for event in self.think_stream(messages, temperature):
                token = event["token"]
                if event["kind"] == "reasoning":
                    if not has_reasoning:
                        print(dim("  [Deep Think]"))
                        has_reasoning = True
                    print(dim(token), end="", flush=True)
                else:
                    if has_reasoning and not collected_content:
                        print()  # reasoning 结束后换行
                    print(token, end="", flush=True)
                    collected_content.append(token)
        except Exception:
            pass  # think_stream 内已 yield 错误信息

        print()  # 输出结束后换行
        full = "".join(collected_content)
        return full if full.strip() else None
