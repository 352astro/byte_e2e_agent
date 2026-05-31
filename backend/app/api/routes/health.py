from fastapi import APIRouter

from app.schemas.response import StreamEventSchema

router = APIRouter()


@router.get("/")
def root() -> dict[str, str]:
    return {"message": "Hello World from FastAPI!"}


@router.get("/api/hello")
def hello() -> dict[str, str]:
    return {"message": "Hello World from FastAPI!", "status": "ok"}


@router.get(
    "/api/sse-schema",
    response_model=StreamEventSchema,
    summary="SSE event schema (for documentation / codegen)",
    description="Returns the StreamEvent structure used in SSE streams. Not a real endpoint.",
)
def sse_schema():
    """Dummy endpoint to expose StreamEvent in OpenAPI for frontend codegen."""
    return {
        "kind": "message_start",
        "message_id": "",
        "turn_id": "",
        "field": "",
        "delta": "",
        "full_content": "",
        "tool_name": "",
        "tool_args": "",
        "is_error": False,
        "input_tokens": 0,
        "output_tokens": 0,
        "reason": "",
    }
