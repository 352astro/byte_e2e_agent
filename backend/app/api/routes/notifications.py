"""Global notification SSE stream + recover endpoint."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.dependencies import get_context as get_workspace_context
from app.services.workspace_context import WorkspaceContext
from shared.types import StreamEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _sse_event_line(ev: StreamEvent) -> str:
    data = json.dumps(ev.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    return f"data: {data}\n\n"


@router.get("/stream")
async def notification_stream(
    ctx: WorkspaceContext = Depends(get_workspace_context),
):
    """Subscribe to global notification events (guard requests, notices, subagent lifecycle)."""
    driver = ctx.notification_driver
    q = driver.subscribe(replay_buffer=True)

    async def event_generator():
        try:
            while True:
                event = await q.get()
                if event is None:
                    break
                yield _sse_event_line(event)
                q.task_done()
        except asyncio.CancelledError:
            pass
        finally:
            driver.unsubscribe(q)

    async def generator_with_heartbeat():
        # Send an initial heartbeat so the client knows the stream is open
        heartbeat = json.dumps({"kind": "heartbeat"})
        yield f"data: {heartbeat}\n\n"
        async for line in event_generator():
            yield line

    return StreamingResponse(
        generator_with_heartbeat(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/recover")
async def notification_recover(
    ctx: WorkspaceContext = Depends(get_workspace_context),
):
    """Return current notification state (pending guard, active notices, subagent status)."""
    return ctx.notification_driver.build_recover_payload()


class NotificationRespondRequest(BaseModel):
    response: dict


@router.post("/respond/{request_id}")
async def notification_respond(
    request_id: str,
    req: NotificationRespondRequest,
    ctx: WorkspaceContext = Depends(get_workspace_context),
):
    """Respond to a pending guard request by its request_id."""
    # Resolve on the runtime (which holds _pending)
    runtime = ctx.runtime
    try:
        await runtime.resolve(request_id, req.response)
    except KeyError:
        raise HTTPException(status_code=404, detail="Pending request not found") from None

    # Clear the pending guard display state
    ctx.notification_driver.resolve_guard(request_id)
    return {"ok": True}
