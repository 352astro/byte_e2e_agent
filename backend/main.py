from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings
from app.core.cors import setup_cors
from app.services.workspace_registry import register_workspace


@asynccontextmanager
async def lifespan(_app: FastAPI):
    register_workspace(get_settings().agent_workspace)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_title, lifespan=lifespan)
    setup_cors(app, settings)
    app.include_router(api_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
