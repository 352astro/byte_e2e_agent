from fastapi import APIRouter, Depends, Query

from app.dependencies import get_project
from app.services.project import Project

router = APIRouter(prefix="/api/metrics/llm", tags=["metrics"])


@router.get("/calls")
def list_llm_calls(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session_id: str | None = None,
    project: Project = Depends(get_project),
) -> dict:
    return project.list_llm_calls(
        limit=limit,
        offset=offset,
        session_id=session_id,
    )


@router.get("/summary")
def get_llm_summary(
    session_id: str | None = None,
    project: Project = Depends(get_project),
) -> dict:
    return project.get_llm_summary(session_id=session_id)


@router.get("/dashboard")
def get_llm_dashboard(
    limit: int = Query(default=20, ge=1, le=100),
    session_id: str | None = None,
    project: Project = Depends(get_project),
) -> dict:
    return project.get_llm_dashboard(
        limit=limit,
        session_id=session_id,
    )
