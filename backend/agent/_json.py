"""
安全的 JSON 解析工具。

LLM 输出的 JSON 偶尔带有微小的格式瑕疵（前缀杂质、末尾多余字符等），
直接打回重试浪费 token 和延迟。本模块提供两层自愈：

    Tier 1 — 直接解析（最快路径）
    Tier 2 — json-repair 修复后解析（格式小毛病）
    Tier 3 — 抛出异常，由调用方决定是否打回 LLM
"""

import json as _json

from pydantic import BaseModel, ValidationError


def safe_parse_json(raw: str, model_cls: type[BaseModel]) -> BaseModel:
    """Parse a (possibly malformed) JSON string into a Pydantic model.

    Tries direct parsing first; if that fails, attempts repair via the
    optional ``json_repair`` library before falling back to the caller.

    Raises ``ValidationError`` only when all tiers have been exhausted.
    """
    # ── Tier 1: direct parse ─────────────────────────
    try:
        return model_cls.model_validate_json(raw)
    except ValidationError:
        pass  # fall through to repair

    # ── Tier 2: json-repair ──────────────────────────
    try:
        from json_repair import repair_json  # type: ignore[import-untyped]

        repaired = repair_json(raw)
        # Quick sanity: repair must produce valid JSON
        _json.loads(repaired)
        return model_cls.model_validate_json(repaired)
    except ImportError:
        pass  # optional dependency not installed
    except (ValidationError, ValueError):
        pass  # repaired string still invalid

    # ── Tier 3: give up ─────────────────────────────
    # Re-raise the original error for the caller to handle
    return model_cls.model_validate_json(raw)
