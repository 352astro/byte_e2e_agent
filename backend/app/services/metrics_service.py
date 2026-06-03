"""LLM metrics queries."""

from __future__ import annotations

from typing import Any

from app.services.context import WorkspaceContext


class MetricsService:
    def __init__(self, ctx: WorkspaceContext) -> None:
        self._ctx = ctx

    # ── Calls ─────────────────────────────────────────

    def list_llm_calls(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        session_id: str | None = None,
        message_id: str | None = None,
        workspace_root: str | None = None,
    ) -> dict[str, Any]:
        return self._ctx.metrics_store.list_calls(
            limit=limit,
            offset=offset,
            session_id=session_id,
            message_id=message_id,
            workspace_root=workspace_root,
        )

    def get_llm_summary(
        self,
        session_id: str | None = None,
        workspace_root: str | None = None,
    ) -> dict[str, Any]:
        return self._ctx.metrics_store.summary(
            session_id=session_id,
            workspace_root=workspace_root,
        )

    def get_llm_dashboard(
        self,
        *,
        limit: int = 20,
        session_id: str | None = None,
        workspace_root: str | None = None,
    ) -> dict[str, Any]:
        return self._ctx.metrics_store.dashboard(
            limit=limit,
            session_id=session_id,
            workspace_root=workspace_root,
        )

    def get_llm_series(
        self,
        *,
        span: str = "week",
        workspace_root: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        return self._ctx.metrics_store.series(
            span=span,
            workspace_root=workspace_root,
            model=model,
        )

    # ── Pricing ───────────────────────────────────────

    def list_pricing(self) -> list[dict[str, Any]]:
        return self._ctx.metrics_store.list_pricing()

    def upsert_pricing(
        self,
        model_id: str,
        input_price: float,
        output_price: float,
        reasoning_price: float | None = None,
        cached_input_price: float | None = None,
    ) -> None:
        self._ctx.metrics_store.upsert_pricing(
            model_id,
            input_price,
            output_price,
            reasoning_price,
            cached_input_price,
        )

    def delete_pricing(self, model_id: str) -> None:
        self._ctx.metrics_store.delete_pricing(model_id)
