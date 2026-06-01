"""Side-query 客户端 — memory 模块内部使用。

── 环境变量 ──
  SIDE_LLM_API_KEY  → fallback LLM_API_KEY
  SIDE_LLM_BASE_URL → fallback LLM_BASE_URL
  SIDE_LLM_MODEL_ID → fallback LLM_MODEL_ID
"""

from __future__ import annotations

import os


def create_side_client():
    """为摘要/检索等 side query 创建 OpenAI 客户端。"""
    from openai import OpenAI

    api_key = os.getenv("SIDE_LLM_API_KEY") or os.getenv("LLM_API_KEY", "")
    if not api_key:
        raise ValueError("SIDE_LLM_API_KEY or LLM_API_KEY must be set")

    base_url = os.getenv("SIDE_LLM_BASE_URL") or os.getenv("LLM_BASE_URL", "")

    kwargs: dict = dict(api_key=api_key)
    if base_url:
        kwargs["base_url"] = base_url

    return OpenAI(**kwargs)


def get_side_model_id() -> str:
    """获取 side query 模型 ID。"""
    return os.getenv("SIDE_LLM_MODEL_ID") or os.getenv("LLM_MODEL_ID", "gpt-4o")
