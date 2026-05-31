"""Chat routes — SSE streaming via StreamDriverHook.

新设计：SSE 事件直接是 StreamEvent.model_dump(mode='json')。
前端 msg[ev.field] += ev.delta 镜像构建 Message。
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException

from app.api.sse import sse_response
from app.dependencies import get_project
from app.schemas.chat import ChatRequest, RespondRequest
from app.services.project import Project
from shared.types import StreamEvent, StreamEventKind

router = APIRouter(prefix="/api/session/{sid}")


def _sse_event_line(event) -> str:
    """将 StreamEvent (Pydantic) 序列化为 SSE line。"""
    data = event.model_dump(mode="json")
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _message_replay_events(msg: dict):
    """将已完成 Message dict 转换为 StreamEvent 序列（用于 SSE 回放）。"""
    msg_id = msg.get("id", "")
    turn_id = msg.get("turn_id", "")
    role = msg.get("role", "")

    # 1) message_start
    yield StreamEvent(
        kind=StreamEventKind.MESSAGE_START,
        message_id=msg_id,
        turn_id=turn_id,
        role=role,
    )

    # 2) content
    content = msg.get("content", "")
    if content:
        yield StreamEvent.chunk_delta(msg_id, "content", content)
        yield StreamEvent.chunk_complete(msg_id, "content", content)

    # 3) reasoning
    reasoning = msg.get("reasoning", "")
    if reasoning:
        yield StreamEvent.chunk_delta(msg_id, "reasoning", reasoning)
        yield StreamEvent.chunk_complete(msg_id, "reasoning", reasoning)

    # 4) tool_calls
    for i, tc in enumerate(msg.get("tool_calls", []) or []):
        fn = tc.get("function", {})
        name = fn.get("name", "")
        args = fn.get("arguments", "")
        if name:
            yield StreamEvent.chunk_delta(
                msg_id, "tool_calls", name,
                tool_name=name, tool_index=i, sub_field="name",
            )
        if args:
            yield StreamEvent.chunk_delta(
                msg_id, "tool_calls", args,
                tool_name=name, tool_index=i, sub_field="args",
            )
        yield StreamEvent.chunk_complete(
            msg_id, "tool_calls", args,
            tool_name=name, tool_args=args,
        )

    # 5) tool_result
    tool_result = msg.get("tool_result", "")
    if tool_result:
        yield StreamEvent.chunk_delta(msg_id, "tool_result", tool_result)
        yield StreamEvent.chunk_complete(
            msg_id, "tool_result", tool_result,
            tool_name=msg.get("tool_name", ""),
            is_error=bool(msg.get("error", "")),
        )

    # 6) message_finish
    yield StreamEvent.message_finish(msg_id)


@router.post("/chat")
async def chat(
    sid: str,
    req: ChatRequest,
    project: Project = Depends(get_project),
):
    """启动执行，返回 SSE 流。

    subscribe-before-start: driver 先订阅，再启动 runtime。
    """
    try:
        stream = project.start_chat(sid, req.question, req.max_steps)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    q = stream.queue

    async def event_generator():
        try:
            while True:
                ev = await q.get()
                if ev is None:
                    break
                yield _sse_event_line(ev)
        except asyncio.CancelledError:
            pass
        finally:
            stream.driver.unsubscribe(q)

    return sse_response(event_generator())


@router.get("/stream")
async def stream_events(sid: str, project: Project = Depends(get_project)):
    """SSE 重连。先回放历史消息，再订阅直播。"""
    try:
        stream = project.get_stream(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    driver = stream.driver
    session = stream.session

    async def event_generator():
        # 回放已完成的历史消息（StreamEvent 格式）
        for msg in session.get_messages():
            for ev in _message_replay_events(msg):
                yield _sse_event_line(ev)

        if driver is None:
            return

        q = driver.subscribe()
        try:
            # 直播事件
            while True:
                ev = await q.get()
                if ev is None:
                    break
                yield _sse_event_line(ev)
        except asyncio.CancelledError:
            pass
        finally:
            driver.unsubscribe(q)

    return sse_response(event_generator())


@router.post("/respond")
async def respond(
    sid: str,
    req: RespondRequest,
    project: Project = Depends(get_project),
):
    try:
        scheduler = project.scheduler
        scheduler.resolve(req.message_id, req.response)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}
