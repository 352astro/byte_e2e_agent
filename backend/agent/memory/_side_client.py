"""Side-query 客户端 — memory 模块内部使用。

── 环境变量 ──
  SIDE_LLM_API_KEY  → fallback LLM_API_KEY
  SIDE_LLM_BASE_URL → fallback LLM_BASE_URL
  SIDE_LLM_MODEL_ID → fallback LLM_MODEL_ID

All read via get_settings(), never direct os.getenv.
"""

from __future__ import annotations

from app.core.config import get_settings


def create_side_client():
    """为摘要/检索等 side query 创建 OpenAI 客户端。"""
    from openai import OpenAI

    settings = get_settings()
    api_key = settings.side_llm_api_key or settings.llm_api_key
    if not api_key:
        raise ValueError("SIDE_LLM_API_KEY or LLM_API_KEY must be set")

    base_url = settings.side_llm_base_url or settings.llm_base_url

    kwargs: dict = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url

    return OpenAI(**kwargs)


def get_side_model_id() -> str:
    """获取 side query 模型 ID。"""
    settings = get_settings()
    return settings.side_llm_model_id or settings.llm_model_id
