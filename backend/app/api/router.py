from fastapi import APIRouter

from app.api.routes import (
    chat,
    health,
    memory,
    metrics,
    notifications,
    sessions,
    settings,
    workspace,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(workspace.router)
api_router.include_router(sessions.router)
api_router.include_router(settings.router)
api_router.include_router(chat.router)
api_router.include_router(metrics.router)
api_router.include_router(memory.router)
api_router.include_router(notifications.router)
