"""OpenAI LLM 适配层。

── 职责 ──
- 创建 openai.OpenAI 客户端
- 提供模型配置工厂
"""

from __future__ import annotations

from openai import OpenAI

from app.core.config import get_settings


def create_client(
    model_id: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int | None = None,
) -> OpenAI:
    """创建 openai.OpenAI 客户端。

    Args:
        model_id: 模型 ID（默认从 Settings 读取）
        api_key: API key（默认从 Settings 读取）
        base_url: API base URL（默认从 Settings 读取）
        timeout: 超时时间（秒）
    Returns:
        (client, model_id) — 客户端实例和解析后的 model_id
    """
    settings = get_settings()
    api_key = api_key or settings.llm_api_key
    if not api_key:
        raise ValueError("LLM_API_KEY must be set in environment or passed explicitly")

    kwargs: dict = dict(api_key=api_key)
    base_url = base_url or settings.llm_base_url
    if base_url:
        kwargs["base_url"] = base_url
    if timeout is not None:
        kwargs["timeout"] = timeout

    return OpenAI(**kwargs)


def get_model_id() -> str:
    """获取模型 ID（从 Settings）。"""
    return get_settings().llm_model_id


def create_client_from_env() -> OpenAI:
    """从 Settings 创建客户端（最简用法）。"""
    settings = get_settings()
    return create_client(timeout=settings.llm_timeout)
