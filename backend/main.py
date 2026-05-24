from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings
from app.core.cors import setup_cors

def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_title)
    setup_cors(app, settings)
    app.include_router(api_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
