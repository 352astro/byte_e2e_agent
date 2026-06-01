"""LLM metrics queries."""

from __future__ import annotations

from typing import Any

from app.services.context import WorkspaceContext


class MetricsService:
    def __init__(self, ctx: WorkspaceContext) -> None:
        self._ctx = ctx

    def list_llm_calls(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return self._ctx.metrics_store.list_calls(
            limit=limit,
            offset=offset,
            session_id=session_id,
        )

    def get_llm_summary(self, session_id: str | None = None) -> dict[str, Any]:
        return self._ctx.metrics_store.summary(session_id=session_id)

    def get_llm_dashboard(
        self,
        *,
        limit: int = 20,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return self._ctx.metrics_store.dashboard(limit=limit, session_id=session_id)
