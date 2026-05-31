"""Scheduler — 单例执行调度器。

一个 Project 只有一个 Scheduler，一次只运行一个 Session。
持有运行时状态（_current_session、_interrupt_event），编排 ReAct 循环。
核心逻辑在 agent.actions 中。
"""

from __future__ import annotations

import asyncio
import uuid as _uuid

from agent.actions import (
    _apply_repairs,
    _default_toolset,
    execute_one_tool,
    model_call,
)
from agent.errors import InterruptedError, ToolMismatchError
from agent.prompts import SYSTEM_PROMPT
from agent.sandbox import Sandbox
from agent.session import Session
from agent.shadow_repo import ShadowRepo
from agent.tools.shell import get_platform_hint
from agent.tools.skill import skill_context_message
from agent.tools.task import task_context_message
from agent.transcript import TranscriptStream
from agent.config import DEFAULT_TMP_DIR as TMP_DIR


class Scheduler:
    """Per-Project 执行调度器（单例）。

    一次只允许一个 Session 在运行。
    TranscriptStream 是 per-execution 的临时通道。
    """

    def __init__(self) -> None:
        self._state: str = "idle"
        self._loop_task: asyncio.Task | None = None
        self._pending: dict[str, dict] = {}
        self._current_session: Session | None = None
        self._current_channel: TranscriptStream | None = None
        self._shadow_repo: ShadowRepo | None = None
        self._interrupt_event: asyncio.Event | None = None

    # ── public ────────────────────────────────────────────

    @property
    def channel(self) -> TranscriptStream | None:
        return self._current_channel

    @property
    def state(self) -> str:
        return self._state

    @property
    def pending_request(self) -> dict | None:
        if self._state != "awaiting_input":
            return None
        for tid, pending in self._pending.items():
            return {
                "transcript_id": tid,
                "kind": pending.get("kind", "permission_request"),
                "message": pending.get("message", {}),
            }
        return None

    def is_running_session(self, session_id: str) -> bool:
        return (
            self._state != "idle"
            and self._current_session is not None
            and self._current_session.session_id == session_id
        )

    def start(
        self,
        session: Session,
        question: str,
        channel: TranscriptStream | None = None,
        max_steps: int = 50,
        shadow_repo: ShadowRepo | None = None,
    ) -> str:
        if self._state != "idle":
            raise RuntimeError(f"Scheduler already running (state={self._state})")
        self._current_session = session
        self._current_channel = channel if channel is not None else TranscriptStream()
        self._shadow_repo = shadow_repo
        self._interrupt_event = asyncio.Event()
        self._state = "running"
        self._loop_task = asyncio.create_task(
            self._query_loop(question, max_steps),
            name="sched",
        )
        return session.session_id

    def resolve(self, transcript_id: str, response: dict) -> None:
        pending = self._pending.get(transcript_id)
        if pending is None:
            raise KeyError(f"No pending request: {transcript_id}")
        pending["response"] = response
        pending["event"].set()

    async def interrupt(self) -> bool:
        if self._interrupt_event is None:
            return False
        self._interrupt_event.set()
        task = self._loop_task
        if task is not None:
            try:
                await task
            except Exception:
                pass
        return True

    # ═══════════════════════════════════════════════════
    # query loop
    # ═══════════════════════════════════════════════════

    async def _query_loop(self, question: str, max_steps: int) -> None:
        session = self._current_session
        channel = self._current_channel
        assert session is not None and channel is not None
        intr = self._interrupt_event
        assert intr is not None

        llm_client = session.llm_client
        sid = session.session_id

        try:
            session._sandbox.reset_terminal()

            is_first = (
                self._shadow_repo is not None
                and len(self._shadow_repo.list_commits(sid)) == 0
            )
            user_id = _uuid.uuid4().hex
            if is_first and self._shadow_repo is not None:
                try:
                    self._shadow_repo.snapshot(
                        sid,
                        "Initial workspace state",
                        transcript_id="__init__",
                    )
                except Exception:
                    pass

            user_msg = {"role": "user", "content": question}
            t = await channel.flush(user_id, "user_question", base=user_msg)
            session.add_transcript(t.kind, t.message, t.id)

            for _ in range(max_steps):
                if intr.is_set():
                    raise InterruptedError("Interrupted by user")

                messages: list[dict] = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "system",
                        "content": f"## Platform\n{get_platform_hint()}",
                    },
                    {
                        "role": "system",
                        "content": (
                            f"## System Directory\n"
                            f"The `{TMP_DIR}/` directory at the workspace root is managed by "
                            f"the system for session state, task lists, and internal storage. "
                            f"Do NOT read, edit, create, or delete files under `{TMP_DIR}/` — "
                            f"it is not user code."
                        ),
                    },
                    skill_context_message(),
                    task_context_message(session._sandbox),
                ]
                messages.extend(session.get_messages())

                assistant_id = _uuid.uuid4().hex
                finish_reason = await model_call(
                    llm_client,
                    sid,
                    channel,
                    messages,
                    session._toolset.openai_tools,
                    transcript_id=assistant_id,
                    interrupt_event=intr,
                )

                pre_msg = channel.message
                has_tool_calls = bool(pre_msg and pre_msg.get("tool_calls"))

                t = await channel.flush(assistant_id, "assistant")
                session.add_transcript(t.kind, t.message, t.id)

                if finish_reason == "stop":
                    if self._shadow_repo is not None:
                        try:
                            sha = self._shadow_repo.snapshot(
                                sid,
                                question,
                                transcript_id=user_id,
                            )
                            aid = _uuid.uuid4().hex
                            t = await channel.flush(
                                aid,
                                "commit_attachment",
                                base={"target_tid": user_id, "commit_sha": sha},
                            )
                            session.add_transcript(t.kind, t.message, t.id)
                            for ut in reversed(session._transcripts):
                                if ut.id == user_id and ut.kind == "user_question":
                                    ut.commit_sha = sha
                                    break
                        except Exception:
                            pass
                    return

                if not has_tool_calls:
                    t = await channel.flush(
                        _uuid.uuid4().hex,
                        "error",
                        base={"message": "LLM returned no tool_calls and no content."},
                    )
                    session.add_transcript(t.kind, t.message, t.id)
                    return

                for tc in t.message.get("tool_calls", []):
                    if intr.is_set():
                        raise InterruptedError("Interrupted between tools")

                    await execute_one_tool(
                        tc,
                        session._sandbox,
                        session._toolset,
                        channel,
                        interrupt_event=intr,
                        llm_client=llm_client,
                    )
                    rid = _uuid.uuid4().hex
                    t = await channel.flush(
                        rid,
                        "tool_result",
                        base={
                            "tool_call_id": tc["id"],
                            "tool_name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    )
                    session.add_transcript(t.kind, t.message, t.id)

            if self._shadow_repo is not None:
                try:
                    sha = self._shadow_repo.snapshot(
                        sid,
                        question,
                        transcript_id=user_id,
                    )
                    aid = _uuid.uuid4().hex
                    t = await channel.flush(
                        aid,
                        "commit_attachment",
                        base={"target_tid": user_id, "commit_sha": sha},
                    )
                    session.add_transcript(t.kind, t.message, t.id)
                    for ut in reversed(session._transcripts):
                        if ut.id == user_id and ut.kind == "user_question":
                            ut.commit_sha = sha
                            break
                except Exception:
                    pass

        except ToolMismatchError:
            try:
                await _apply_repairs(session, channel)
                t = await channel.flush(
                    _uuid.uuid4().hex,
                    "error",
                    base={
                        "message": "A tool call / result mismatch was detected. "
                        "The conversation has been repaired. Please continue."
                    },
                )
                session.add_transcript(t.kind, t.message, t.id)
            except Exception:
                pass
        except InterruptedError:
            try:
                await _apply_repairs(session, channel)
                t = await channel.flush(
                    _uuid.uuid4().hex,
                    "error",
                    base={
                        "message": "The user interrupted the agent before it could "
                        "finish. Summarize what you have done so far and ask "
                        "how to proceed."
                    },
                )
                session.add_transcript(t.kind, t.message, t.id)
            except Exception:
                pass
        except Exception as exc:
            import traceback

            traceback.print_exc()
            try:
                await _apply_repairs(session, channel)
                t = await channel.flush(
                    _uuid.uuid4().hex,
                    "error",
                    base={"message": str(exc)},
                )
                session.add_transcript(t.kind, t.message, t.id)
            except Exception:
                pass
        finally:
            self._state = "idle"
            self._loop_task = None
            session._sandbox.reset_browser()
            if self._current_channel is channel:
                channel.close()
                self._current_channel = None
