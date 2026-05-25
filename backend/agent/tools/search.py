"""Search 工具 — SerpApi 网页搜索。"""

import os

import serpapi
from pydantic import Field

from agent.tools.base import BaseTool


class Search(BaseTool):
    query: str = Field(..., description="Search query keywords")
    gl: str = Field(default="cn", description="Country code")
    hl: str = Field(default="zh-cn", description="Language code")

    async def execute(self, sandbox=None) -> str:
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
