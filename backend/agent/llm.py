"""OpenAI LLM 适配层。

── 职责 ──
- 创建 openai.OpenAI 客户端
- 提供模型配置工厂
"""

from __future__ import annotations

import os

from openai import OpenAI


def create_client(
    model_id: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int | None = None,
) -> OpenAI:
    """创建 openai.OpenAI 客户端。

    Args:
        model_id: 模型 ID（默认从 LLM_MODEL_ID 环境变量读取）
        api_key: API key（默认从 LLM_API_KEY 环境变量读取）
        base_url: API base URL（默认从 LLM_BASE_URL 环境变量读取）
        timeout: 超时时间（秒）
    Returns:
        (client, model_id) — 客户端实例和解析后的 model_id
    """
    api_key = api_key or os.getenv("LLM_API_KEY", "")
    if not api_key:
        raise ValueError("LLM_API_KEY must be set in environment or passed explicitly")

    kwargs: dict = dict(api_key=api_key)
    if base_url or os.getenv("LLM_BASE_URL"):
        kwargs["base_url"] = base_url or os.getenv("LLM_BASE_URL", "")
    if timeout is not None:
        kwargs["timeout"] = timeout

    return OpenAI(**kwargs)


def get_model_id() -> str:
    """获取模型 ID（从环境变量）。"""
    return os.getenv("LLM_MODEL_ID", "gpt-4o")


def create_client_from_env() -> OpenAI:
    """从环境变量创建客户端（最简用法）。"""
    timeout_raw = os.getenv("LLM_TIMEOUT", "").strip()
    try:
        timeout = int(timeout_raw) if timeout_raw else None
    except ValueError:
        timeout = None
    return create_client(timeout=timeout)
