"""Metrics response schemas — auto-generated to frontend via OpenAPI."""

from __future__ import annotations

from pydantic import BaseModel


class LLMCallItem(BaseModel):
    id: str
    created_at: str
    workspace_root: str = ""
    session_id: str | None = None
    message_id: str | None = None
    call_type: str
    model: str
    status: str
    finish_reason: str | None = None
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    prompt_cached_tokens: int | None = None
    prompt_cache_hit: int | None = None
    prompt_cache_miss: int | None = None
    cost_yuan: float | None = None
    error: str | None = None


class Pagination(BaseModel):
    limit: int
    offset: int
    total: int


class LLMCallListResponse(BaseModel):
    items: list[LLMCallItem]
    pagination: Pagination


class LLMSummaryResponse(BaseModel):
    total_calls: int = 0
    successful_calls: int = 0
    errored_calls: int = 0
    avg_latency_ms: float | None = None
    min_latency_ms: int | None = None
    max_latency_ms: int | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0
    prompt_cached_tokens: int = 0
    cost_yuan: float | None = None


class LLMDashboardResponse(BaseModel):
    summary: LLMSummaryResponse
    by_model: list[LLMModelBreakdown]
    recent_calls: list[LLMCallItem]


class LLMModelBreakdown(BaseModel):
    model: str
    total_calls: int
    errored_calls: int = 0
    avg_latency_ms: float | None = None
    total_tokens: int = 0
    reasoning_tokens: int = 0
    cost_yuan: float | None = None


class ModelPricingItem(BaseModel):
    model_id: str
    input_price_per_1m: float
    output_price_per_1m: float
    reasoning_price_per_1m: float | None = None
    cached_input_price_per_1m: float | None = None
    is_custom: int = 0
    updated_at: str


class UpsertPricingRequest(BaseModel):
    model_id: str
    input_price: float
    output_price: float
    reasoning_price: float | None = None
    cached_input_price: float | None = None


class LLMSeriesBucket(BaseModel):
    bucket: str
    model: str
    calls: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    cost_yuan: float = 0


class LLMSeriesResponse(BaseModel):
    span: str
    unit: str
    models: list[str]
    buckets: list[LLMSeriesBucket]
