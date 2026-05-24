from fastapi import APIRouter

from app.api.routes import chat, health, metrics, sessions, workspace

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(workspace.router)
api_router.include_router(sessions.router)
api_router.include_router(chat.router)
api_router.include_router(metrics.router)
