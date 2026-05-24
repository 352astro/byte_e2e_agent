from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def root() -> dict[str, str]:
    return {"message": "Hello World from FastAPI!"}


@router.get("/api/hello")
def hello() -> dict[str, str]:
    return {"message": "Hello World from FastAPI!", "status": "ok"}
