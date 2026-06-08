"""Pending approval and AskUser helpers for AgentRuntime."""

from __future__ import annotations

import asyncio
import uuid as _uuid

from agent.errors import InterruptedError
from agent.session.status import SessionStatus
from shared.hooks import GuardCheck


async def ask_guard(runtime, check: GuardCheck, interrupt_event: asyncio.Event) -> bool:
    request_id = _uuid.uuid4().hex
    event = asyncio.Event()
    run = runtime._runs.get(check.session_id)
    pending_store = run.pending if run is not None else runtime._pending
    pending_store[request_id] = {
        "kind": "guard_request",
        "message": {
            "request_id": request_id,
            "action_type": check.action_type,
            "subject": check.subject,
            "payload": check.payload,
            "turn_id": check.turn_id,
            "message_id": check.message_id,
            "tool_call_id": check.tool_call_id,
        },
        "event": event,
    }
    try:
        await runtime._hooks.on_guard_request(request_id=request_id, check=check)
        _, pending = await asyncio.wait(
            {
                asyncio.create_task(event.wait()),
                asyncio.create_task(interrupt_event.wait()),
            },
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if interrupt_event.is_set():
            raise InterruptedError("Interrupted while waiting for approval")
        response = pending_store.get(request_id, {}).get("response", {})
        return bool(response.get("allow") or response.get("approved"))
    finally:
        pending_store.pop(request_id, None)


async def ask_user_input(
    runtime,
    payload: dict,
    interrupt_event: asyncio.Event,
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    tool_call_id: str,
) -> dict:
    request_id = _uuid.uuid4().hex
    event = asyncio.Event()
    message = {
        "kind": "user_input_request",
        "request_id": request_id,
        "action_type": "user.input",
        "subject": payload.get("title") or "AskUser",
        "payload": payload,
        "title": payload.get("title", ""),
        "description": payload.get("description", ""),
        "choices": payload.get("choices", []),
        "questions": payload.get("questions", []),
        "choice_required": bool(payload.get("choice_required", True)),
        "multiple": bool(payload.get("multiple", False)),
        "allow_custom": bool(payload.get("allow_custom", False)),
        "turn_id": turn_id,
        "message_id": message_id,
        "tool_call_id": tool_call_id,
    }
    run = runtime._runs.get(session_id)
    pending_store = run.pending if run is not None else runtime._pending
    pending_store[request_id] = {
        "kind": "user_input_request",
        "message": message,
        "event": event,
    }
    entry = runtime._sessions.get(session_id)
    if entry and entry.status == SessionStatus.RUNNING:
        entry.transition_to(SessionStatus.PENDING)
    try:
        check = GuardCheck(
            action_type="user.input",
            subject=message["subject"],
            payload=message,
            session_id=session_id,
            turn_id=turn_id,
            message_id=message_id,
            tool_call_id=tool_call_id,
        )
        await runtime._hooks.on_guard_request(request_id=request_id, check=check)
        _, pending = await asyncio.wait(
            {
                asyncio.create_task(event.wait()),
                asyncio.create_task(interrupt_event.wait()),
            },
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if interrupt_event.is_set():
            raise InterruptedError("Interrupted while waiting for user input")
        return pending_store.get(request_id, {}).get("response", {})
    finally:
        pending_store.pop(request_id, None)
        if entry and entry.status == SessionStatus.PENDING:
            entry.transition_to(SessionStatus.RUNNING)


async def resolve(runtime, message_id: str, response: dict) -> None:
    run = runtime._run_for_pending(message_id)
    pending_store = run.pending if run is not None else runtime._pending
    pending = pending_store.get(message_id)
    if pending is None:
        raise KeyError(f"No pending request: {message_id}")
    pending["response"] = response
    pending["event"].set()
