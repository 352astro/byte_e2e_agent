"""
安全的 JSON 解析工具。

LLM 输出的 JSON 偶尔带有微小的格式瑕疵（前缀杂质、末尾多余字符等），
直接打回重试浪费 token 和延迟。本模块提供两层自愈：

    Tier 1 — 直接解析（最快路径）
    Tier 2 — json-repair 修复后解析（格式小毛病）
    Tier 3 — 抛出异常，由调用方决定是否打回 LLM
"""

from __future__ import annotations

import json as _json
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError


def safe_parse_json(raw: str, model_cls: type[BaseModel]) -> BaseModel:
    """Parse a (possibly malformed) JSON string into a Pydantic model.

    Tries direct parsing first; if that fails, attempts repair via the
    optional ``json_repair`` library before falling back to the caller.

    Raises ``ValidationError`` only when all tiers have been exhausted.
    """
    return _safe_validate(raw, model_cls.model_validate_json)  # type: ignore[return-value]


def safe_validate_json(raw: str, adapter: TypeAdapter[Any]) -> Any:
    """Parse (possibly malformed) JSON with a ``TypeAdapter``.

    Same three-tier strategy as ``safe_parse_json``, but works with
    Pydantic ``TypeAdapter`` instead of a ``BaseModel`` subclass.
    """
    return _safe_validate(raw, adapter.validate_json)


# ── internal ──────────────────────────────────────────────


def _safe_validate(raw: str, validator: Any) -> Any:
    # Tier 1: direct parse
    try:
        return validator(raw)
    except ValidationError:
        pass

    # Tier 2: json-repair
    try:
        from json_repair import repair_json  # type: ignore[import-untyped]

        repaired = repair_json(raw)
        _json.loads(repaired)  # sanity: must be valid JSON
        return validator(repaired)
    except ImportError:
        pass
    except (ValidationError, ValueError):
        pass

    # Tier 3: give up — re-raise original
    return validator(raw)
