from fastapi import APIRouter, Depends, Query

from app.dependencies import get_metrics_service
from app.schemas.metrics import (
    LLMCallListResponse,
    LLMDashboardResponse,
    LLMSeriesResponse,
    LLMSummaryResponse,
    ModelPricingItem,
    UpsertPricingRequest,
)
from app.services.metrics_service import MetricsService

router = APIRouter(prefix="/api/metrics/llm", tags=["metrics"])


@router.get("/calls", response_model=LLMCallListResponse)
def list_llm_calls(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session_id: str | None = None,
    message_id: str | None = None,
    workspace_root: str | None = None,
    metrics_service: MetricsService = Depends(get_metrics_service),
) -> dict:
    return metrics_service.list_llm_calls(
        limit=limit,
        offset=offset,
        session_id=session_id,
        message_id=message_id,
        workspace_root=workspace_root,
    )


@router.get("/summary", response_model=LLMSummaryResponse)
def get_llm_summary(
    session_id: str | None = None,
    workspace_root: str | None = None,
    metrics_service: MetricsService = Depends(get_metrics_service),
) -> dict:
    return metrics_service.get_llm_summary(
        session_id=session_id,
        workspace_root=workspace_root,
    )


@router.get("/dashboard", response_model=LLMDashboardResponse)
def get_llm_dashboard(
    limit: int = Query(default=20, ge=1, le=100),
    session_id: str | None = None,
    workspace_root: str | None = None,
    metrics_service: MetricsService = Depends(get_metrics_service),
) -> dict:
    return metrics_service.get_llm_dashboard(
        limit=limit,
        session_id=session_id,
        workspace_root=workspace_root,
    )


@router.get("/series", response_model=LLMSeriesResponse)
def get_llm_series(
    span: str = Query(default="week", pattern="^(week|month|year)$"),
    workspace_root: str | None = None,
    model: str | None = None,
    metrics_service: MetricsService = Depends(get_metrics_service),
) -> dict:
    return metrics_service.get_llm_series(
        span=span,
        workspace_root=workspace_root,
        model=model,
    )


# ═══════════════════════════════════════════════════════════
# Model Pricing
# ═══════════════════════════════════════════════════════════


@router.get("/pricing", response_model=list[ModelPricingItem])
def list_pricing(
    metrics_service: MetricsService = Depends(get_metrics_service),
) -> list[dict]:
    return metrics_service.list_pricing()


@router.post("/pricing")
def upsert_pricing(
    req: UpsertPricingRequest,
    metrics_service: MetricsService = Depends(get_metrics_service),
) -> dict:
    metrics_service.upsert_pricing(
        req.model_id,
        req.input_price,
        req.output_price,
        req.reasoning_price,
        req.cached_input_price,
    )
    return {"ok": True}


@router.delete("/pricing/{model_id}")
def delete_pricing(
    model_id: str,
    metrics_service: MetricsService = Depends(get_metrics_service),
) -> dict:
    metrics_service.delete_pricing(model_id)
    return {"ok": True}
