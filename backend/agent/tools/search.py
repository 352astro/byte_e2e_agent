"""WebSearch / WebFetch 工具 — 异步实现，支持中断。"""

from __future__ import annotations

import asyncio
import os

import httpx
import serpapi
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class WebSearchInput(BaseModel):
    """WebSearch 工具输入参数。"""

    gl: str = Field(default="cn", description="Country code")
    hl: str = Field(default="zh-cn", description="Language code")
    query: str = Field(..., description="Search query keywords")


def _do_serpapi_search(query: str, gl: str, hl: str) -> dict:
    """同步执行 SerpApi 搜索（在线程池中调用）。"""
    from app.core.config import get_settings
    api_key = get_settings().serpapi_key
    if not api_key:
        raise RuntimeError("SERPAPI_KEY is not configured in the .env file.")
    client = serpapi.Client()
    return client.search(
        {
            "engine": "google",
            "q": query,
            "api_key": api_key,
            "gl": gl,
            "hl": hl,
        }
    )


def _format_search_results(results: dict, query: str) -> str:
    """格式化 SerpApi 结果为文本。"""
    if "answer_box_list" in results:
        return "\n".join(results["answer_box_list"])
    if "answer_box" in results and "answer" in results["answer_box"]:
        return results["answer_box"]["answer"]
    if "knowledge_graph" in results and "description" in results["knowledge_graph"]:
        return results["knowledge_graph"]["description"]
    if "organic_results" in results and results["organic_results"]:
        snippets = [
            f"[{i + 1}] {res.get('title', '')}\n{res.get('snippet', '')}"
            for i, res in enumerate(results["organic_results"][:3])
        ]
        return "\n\n".join(snippets)
    return f"Sorry, no information found for '{query}'."


async def web_search_handler(
    query: str,
    gl: str = "cn",
    hl: str = "zh-cn",
    *,
    ws=None,
    interrupt_event: asyncio.Event | None = None,
) -> str:
    """搜索网络（SerpApi），通过线程池异步执行，支持中断。"""
    if interrupt_event and interrupt_event.is_set():
        return "[WebSearch interrupted before start]"

    try:
        results = await asyncio.to_thread(_do_serpapi_search, query, gl, hl)
    except RuntimeError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Search error: {exc}"

    if interrupt_event and interrupt_event.is_set():
        return "[WebSearch interrupted]"

    return _format_search_results(results, query)


web_search_tool = StructuredTool.from_function(
    coroutine=web_search_handler,
    name="WebSearch",
    description="Search the web via SerpApi and return top results.",
    args_schema=WebSearchInput,
)


class WebFetchInput(BaseModel):
    """WebFetch 工具输入参数。"""

    max_bytes: int = Field(
        default=50_000,
        ge=1000,
        le=500_000,
        description="Maximum bytes to read from the response body.",
    )
    url: str = Field(..., description="Full URL to fetch (https://...)")


async def web_fetch_handler(
    url: str,
    max_bytes: int = 50_000,
    *,
    ws=None,
    interrupt_event: asyncio.Event | None = None,
) -> str:
    """获取 URL 内容（httpx 异步），支持中断。"""
    if interrupt_event and interrupt_event.is_set():
        return "[WebFetch interrupted before start]"

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": "ByteAgent/1.0"},
            follow_redirects=True,
        ) as client:
            # 轮询式读取，每次检查中断标志
            chunks: list[bytes] = []
            total = 0
            async with client.stream("GET", url) as resp:
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    if interrupt_event and interrupt_event.is_set():
                        await resp.aclose()
                        return "[WebFetch interrupted]"
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= max_bytes:
                        break

            content = b"".join(chunks)
            text = content.decode("utf-8", errors="replace")
            suffix = f"\n\n[Truncated at {total} bytes]" if total >= max_bytes else ""
            return text + suffix

    except httpx.HTTPError as exc:
        return f"Error fetching URL: {exc}"
    except Exception as exc:
        return f"Error fetching URL: {exc}"


web_fetch_tool = StructuredTool.from_function(
    coroutine=web_fetch_handler,
    name="WebFetch",
    description="Fetch a URL and return its content as plain text.",
    args_schema=WebFetchInput,
)
