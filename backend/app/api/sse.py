import json
from collections.abc import Iterable
from typing import Any

from fastapi.responses import StreamingResponse


def sse_line(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_response(generator) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def yield_transcripts_as_flush(session) -> Iterable[str]:
    """Yield all session transcripts as flush SSE lines."""
    for t in session.get_transcripts():
        yield sse_line(
            {
                "event": "flush",
                "transcript_id": t["id"],
                "kind": t["kind"],
                "message": t["message"],
            }
        )
