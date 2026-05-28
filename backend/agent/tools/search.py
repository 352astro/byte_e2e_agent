"""WebSearch / WebFetch 工具。"""

from __future__ import annotations

import os
from urllib.request import urlopen, Request

import serpapi
from pydantic import Field

from agent.tools.base import BaseTool


class WebSearch(BaseTool):
    """Search the web via SerpApi and return top results."""

    gl: str = Field(default="cn", description="Country code")
    hl: str = Field(default="zh-cn", description="Language code")
    query: str = Field(..., description="Search query keywords")

    async def execute(self, *, sandbox=None, channel=None, interrupt_event=None, scheduler=None, toolset=None, result_id="") -> str:
        try:
            api_key = os.getenv("SERPAPI_KEY")
            if not api_key:
                return "Error: SERPAPI_KEY is not configured in the .env file."
            client = serpapi.Client()
            results = client.search(
                {
                    "engine": "google",
                    "q": self.query,
                    "api_key": api_key,
                    "gl": self.gl,
                    "hl": self.hl,
                }
            )
            if "answer_box_list" in results:
                return "\n".join(results["answer_box_list"])
            if "answer_box" in results and "answer" in results["answer_box"]:
                return results["answer_box"]["answer"]
            if (
                "knowledge_graph" in results
                and "description" in results["knowledge_graph"]
            ):
                return results["knowledge_graph"]["description"]
            if "organic_results" in results and results["organic_results"]:
                snippets = [
                    f"[{i + 1}] {res.get('title', '')}\n{res.get('snippet', '')}"
                    for i, res in enumerate(results["organic_results"][:3])
                ]
                return "\n\n".join(snippets)
            return f"Sorry, no information found for '{self.query}'."
        except Exception as e:
            return f"Search error: {e}"


class WebFetch(BaseTool):
    """Fetch a URL and return its content as plain text."""

    url: str = Field(..., description="Full URL to fetch (https://...)")
    max_bytes: int = Field(
        default=50_000,
        ge=1000,
        le=500_000,
        description="Maximum bytes to read from the response body.",
    )

    async def execute(self, *, sandbox=None, channel=None, interrupt_event=None, scheduler=None, toolset=None, result_id="") -> str:
        try:
            req = Request(
                self.url,
                headers={"User-Agent": "ByteAgent/1.0"},
            )
            with urlopen(req, timeout=15) as resp:
                content = resp.read(self.max_bytes)
                text = content.decode("utf-8", errors="replace")
                actual = len(content)
                suffix = (
                    f"\n\n[Truncated at {actual} bytes]"
                    if actual >= self.max_bytes
                    else ""
                )
                return text + suffix
        except Exception as exc:
            return f"Error fetching URL: {exc}"
