import os
from typing import Literal

import serpapi
from pydantic import Field

from agent.utils._term import magenta
from agent.tools.base import BaseTool


class Search(BaseTool):
    """
    基于 SerpApi 的网页搜索 Pydantic 模型。
    封装了搜索参数，并提供了 execute() 方法执行搜索。
    """

    kind: Literal["Search"] = "Search"
    query: str = Field(..., description="Search query keywords")
    gl: str = Field(default="cn", description="Country code (gl parameter)")
    hl: str = Field(default="zh-cn", description="Language code (hl parameter)")

    def execute(self) -> str:
        """执行搜索并返回解析后的结果。"""
        return _do_search(self.query, self.gl, self.hl)


def _do_search(query: str, gl: str = "cn", hl: str = "zh-cn") -> str:
    """内部搜索实现。"""
    print(magenta(f"[Search] {query}"))
    try:
        api_key = os.getenv("SERPAPI_KEY")
        if not api_key:
            return "Error: SERPAPI_KEY is not configured in the .env file."

        params = {
            "engine": "google",
            "q": query,
            "api_key": api_key,
            "gl": gl,
            "hl": hl,
        }

        client = serpapi.Client()
        results = client.search(params)

        # 智能解析:优先寻找最直接的答案
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

    except Exception as e:
        return f"Search error: {e}"


def search(query: str) -> str:
    """
    一个基于SerpApi的实战网页搜索引擎工具（便捷函数）。
    它会智能地解析搜索结果，优先返回直接答案或知识图谱信息。
    """
    return _do_search(query)


# ============================================================
# 示范：Schema 生成 与 正反序列化
# ============================================================
if __name__ == "__main__":
    # --- 1. 生成 JSON Schema ---
    schema = Search.model_json_schema()
    print("========== JSON Schema ==========")
    import json

    print(json.dumps(schema, indent=2, ensure_ascii=False))

    # --- 2. 正向：实例化并序列化 ---
    s = Search(query="Python Pydantic 教程")

    # 2a. 序列化为 dict
    dict_data = s.model_dump()
    print("\n========== model_dump() -> dict ==========")
    print(dict_data)

    # 2b. 序列化为 JSON 字符串
    json_str = s.model_dump_json(indent=2)
    print("\n========== model_dump_json() -> str ==========")
    print(json_str)

    # --- 3. 反向：从 dict / JSON 反序列化 ---

    # 3a. 从 dict 反序列化
    s_from_dict = Search.model_validate(dict_data)
    print("\n========== model_validate(dict) ==========")
    print(f"query={s_from_dict.query!r}, gl={s_from_dict.gl!r}, hl={s_from_dict.hl!r}")

    # 3b. 从 JSON 字符串反序列化
    s_from_json = Search.model_validate_json(json_str)
    print("\n========== model_validate_json(str) ==========")
    print(f"query={s_from_json.query!r}, gl={s_from_json.gl!r}, hl={s_from_json.hl!r}")
