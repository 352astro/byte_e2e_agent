"""AgentRuntime — 多 Session 管理 + Hook 注入 + ReAct 主循环。

── 设计原则 ──
- 对标 Rust runtime.rs: AgentRuntime 是中央编排器
- 主循环拥有 messages 和 errors 的完整所有权
- Hook 只收通知（metrics, logging, SSE），抛异常不影响主循环
- 一次只允许一个 Session 处于 RUNNING 状态

── 对标 ──
- Rust: byte_e2e_agent_rs/src/core/runtime.rs
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid as _uuid
from dataclasses import dataclass

from agent.core.config import SessionConfig
from agent.core.workspace import Workspace
from agent.runtime.guard import ask_guard, ask_user_input, resolve
from agent.runtime.messages import (
    emit_error_message,
    finish_partial_streaming_message,
)
from agent.runtime.subagents import (
    create_and_run_subagent,
    invoke_browser_inspect,
    invoke_existing_session,
)
from agent.runtime.turn import execute_turn
from agent.session import load_session
from agent.session.session_entry import RuntimeSession
from agent.session.status import RuntimeStatus, SessionStatus
from shared.hooks import HookManager
from shared.types import Message

# ═══════════════════════════════════════════════════════════
# AgentRuntime
# ═══════════════════════════════════════════════════════════


@dataclass
class RunState:
    """Mutable state for one currently executing session."""

    session_id: str
    entry: RuntimeSession
    interrupt_event: asyncio.Event
    task: asyncio.Task | None = None
    streaming_holder: list[Message | None] | None = None
    pending: dict[str, dict] | None = None

    def __post_init__(self) -> None:
        if self.pending is None:
            self.pending = {}


class AgentRuntime:
    """Per-Project 执行运行时（对标 Rust AgentRuntime）。

    多个顶层 Session 可以并行运行；同一个 Session 仍然一次只允许一个 Turn。

    用法:
        workspace = Workspace("/path/to/project", workspace_uuid="...")
        hooks = HookManager([StreamDriverHook(), LoggingHook()])
        runtime = AgentRuntime(workspace, hooks)

        session = runtime.create_session(SessionConfig.user_main("main", "gpt-4"))
        await runtime.invoke_user(session, "帮我写一个函数")
    """

    def __init__(
        self,
        workspace: Workspace | None = None,
        hook_manager: HookManager | None = None,
        llm=None,  # (openai_client, model_id) tuple (None = 按需创建)
    ) -> None:
        if workspace is None:
            raise ValueError("AgentRuntime requires a Workspace with root and uuid")
        self._workspace = workspace
        self._hooks = hook_manager or HookManager()
        self._llm = llm  # (client, model_id) tuple (lazy init if None)
        self._sessions: dict[str, RuntimeSession] = {}
        self._runs: dict[str, RunState] = {}
        # Compatibility mirrors for older tests/callers. Runtime authority lives
        # in _runs; these point at the first active run when one exists.
        self._running_session_id: str | None = None
        self._interrupt_event: asyncio.Event | None = None
        self._loop_task: asyncio.Task | None = None
        self._pending: dict[str, dict] = {}
        self._streaming_holder: list[Message | None] | None = None

    # ── 属性 ────────────────────────────────────────────

    @property
    def hooks(self) -> HookManager:
        return self._hooks

    @property
    def workspace(self) -> Workspace:
        return self._workspace

    @property
    def status(self) -> RuntimeStatus:
        if self._runs:
            return RuntimeStatus.RUNNING
        return RuntimeStatus.IDLE

    @property
    def current_message(self) -> Message | None:
        """当前正在流式构建中的 Message（供 /recover 使用）。

        仅在 Agent 运行且 LLM 正在输出时非 None。
        """
        if self._running_session_id:
            return self.current_message_for_session(self._running_session_id)
        return None

    @property
    def pending_request(self) -> dict | None:
        """当前待处理的权限请求。"""
        if self._running_session_id:
            req = self.pending_request_for_session(self._running_session_id)
            if req is not None:
                return req
        for mid, pending in self._pending.items():
            return {
                "message_id": mid,
                "kind": pending.get("kind", "permission_request"),
                "message": pending.get("message", {}),
            }
        return None

    # ── Session 管理 ────────────────────────────────────

    def create_session(
        self,
        config: SessionConfig,
        session_id: str | None = None,
        llm_client=None,
        workspace: Workspace | None = None,
    ) -> RuntimeSession:
        """创建新 Session。

        Args:
            config: Session 不可变配置
            session_id: 可选预定义 ID（不提供则自动生成）
            llm_client: LLM 客户端
            workspace: Workspace 实例
        """
        workspace = workspace or self._workspace
        sid = session_id or _uuid.uuid4().hex[:12]
        self._workspace.ensure_dirs(sid)
        self._workspace.save_session_config(sid, config)

        # Write immutable prefix messages (KV-cache anchor) once at creation.
        # Skip if the JSONL already has content (e.g. server restart re-loading
        # an existing session — the prefix was written when the session was
        # first created).
        messages_path = self._workspace.messages_path(sid)
        messages_path.touch(exist_ok=True)
        if messages_path.stat().st_size == 0:
            from agent.session import write_session_prefix

            write_session_prefix(self._workspace, sid, config)

        transcript = load_session(sid, workspace=workspace, repair=False)
        entry = RuntimeSession(
            id=sid,
            config=config,
            llm_client=llm_client,
            workspace=workspace,
            transcript=transcript,
        )
        self._sessions[sid] = entry
        return entry

    def get_session(self, session_id: str) -> RuntimeSession | None:
        """获取已有 Session。"""
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[str]:
        """列出所有已知 Session ID（内存 + 磁盘）。"""
        disk_ids = self._workspace.list_session_ids()
        mem_ids = list(self._sessions.keys())
        all_ids = list(dict.fromkeys(disk_ids + mem_ids))
        all_ids.sort()
        return all_ids

    def _get_llm(self):
        """获取 openai 客户端和 model_id（首次访问时懒加载）。"""
        if self._llm is not None:
            return self._llm
        from agent.llm import create_client_from_env, get_model_id

        self._llm = (create_client_from_env(), get_model_id())
        return self._llm

    def is_running_session(self, session_id: str) -> bool:
        """检查指定 session 是否正在运行。"""
        return session_id in self._runs

    def current_message_for_session(self, session_id: str) -> Message | None:
        run = self._runs.get(session_id)
        if run is None or run.streaming_holder is None:
            return None
        return run.streaming_holder[0]

    def pending_request_for_session(self, session_id: str) -> dict | None:
        run = self._runs.get(session_id)
        if run is None:
            return None
        for mid, pending in (run.pending or {}).items():
            return {
                "message_id": mid,
                "kind": pending.get("kind", "permission_request"),
                "message": pending.get("message", {}),
            }
        return None

    def _sync_legacy_state(self) -> None:
        first = next(iter(self._runs.values()), None)
        self._running_session_id = first.session_id if first else None
        self._interrupt_event = first.interrupt_event if first else None
        self._loop_task = first.task if first else None
        self._pending = first.pending if first and first.pending is not None else {}
        self._streaming_holder = first.streaming_holder if first else None

    def _run_for_pending(self, request_id: str) -> RunState | None:
        for run in self._runs.values():
            if request_id in (run.pending or {}):
                return run
        return None

    def _interrupt_event_for(self, session_id: str) -> asyncio.Event:
        run = self._runs.get(session_id)
        if run is None:
            raise RuntimeError(f"Session {session_id} is not running")
        return run.interrupt_event

    def _set_streaming_holder(
        self,
        session_id: str,
        holder: list[Message | None] | None,
    ) -> None:
        run = self._runs.get(session_id)
        if run is None:
            return
        run.streaming_holder = holder
        self._sync_legacy_state()

    def _begin_run(
        self,
        entry: RuntimeSession,
        *,
        interrupt_event: asyncio.Event | None = None,
    ) -> RunState:
        if entry.id in self._runs:
            raise RuntimeError(f"Runtime already running session {entry.id}")
        run = RunState(
            session_id=entry.id,
            entry=entry,
            interrupt_event=interrupt_event or asyncio.Event(),
        )
        self._runs[entry.id] = run
        entry.transition_to(SessionStatus.RUNNING)
        self._sync_legacy_state()
        return run

    def _finish_run(self, session_id: str) -> None:
        self._runs.pop(session_id, None)
        self._sync_legacy_state()

    def _start_entry(
        self,
        entry: RuntimeSession,
        question: str,
        *,
        max_steps: int = 50,
        shadow_repo=None,
    ) -> str:
        run = self._begin_run(entry)
        task = asyncio.create_task(
            self._execute_turn(entry, question, max_steps, shadow_repo),
            name=f"runtime-{entry.id}",
        )
        run.task = task
        task.add_done_callback(
            lambda done_task, sid=entry.id: self._on_run_task_done(sid, done_task)
        )
        self._sync_legacy_state()
        return entry.id

    def _on_run_task_done(self, session_id: str, task: asyncio.Task) -> None:
        run = self._runs.get(session_id)
        if run is not None and run.task is task:
            if run.entry.status.is_busy():
                run.entry.transition_to(SessionStatus.IDLE)
            self._finish_run(session_id)
        with contextlib.suppress(asyncio.CancelledError, Exception):
            task.exception()

    # ── Invoke: 用户 ────────────────────────────────────

    async def invoke_user(
        self,
        session: RuntimeSession,
        question: str,
        *,
        max_steps: int = 50,
        shadow_repo=None,
    ) -> str:
        """用户发送消息，开始一个 Turn。

        对标 Rust AgentRuntime::invoke_user()。

        Args:
            session: RuntimeSession
            question: 用户问题
            max_steps: ReAct 最大步数
            shadow_repo: Git 快照仓库（可选）

        Returns:
            session_id

        Raises:
            RuntimeError: 如果已有 Session 在运行
        """
        return self._start_entry(
            session,
            question,
            max_steps=max_steps,
            shadow_repo=shadow_repo,
        )

    def start(
        self,
        session: RuntimeSession,
        question: str,
        *,
        max_steps: int = 50,
        shadow_repo=None,
    ) -> str:
        """同步启动（fire-and-forget），供同步上下文使用。"""
        return self._start_entry(
            session,
            question,
            max_steps=max_steps,
            shadow_repo=shadow_repo,
        )

    # ── Invoke: Agent → Agent ────────────────────────────

    async def invoke_existing_session(
        self,
        caller_id: str,
        target_id: str,
        task: str,
        *,
        max_turns: int | None = None,
        parent_message_id: str = "",
        parent_tool_call_id: str = "",
    ) -> str:
        return await invoke_existing_session(
            self,
            caller_id,
            target_id,
            task,
            max_turns=max_turns,
            parent_message_id=parent_message_id,
            parent_tool_call_id=parent_tool_call_id,
        )

    async def create_and_run_subagent(
        self,
        caller_id: str,
        task: str,
        *,
        max_steps: int = 5,
        with_skills: list[str] | None = None,
        parent_message_id: str = "",
        parent_tool_call_id: str = "",
    ) -> str:
        return await create_and_run_subagent(
            self,
            caller_id,
            task,
            max_steps=max_steps,
            with_skills=with_skills,
            parent_message_id=parent_message_id,
            parent_tool_call_id=parent_tool_call_id,
        )

    async def invoke_browser_inspect(
        self,
        caller_id: str,
        *,
        url: str,
        prompt: str,
        max_steps: int = 8,
        parent_message_id: str = "",
        parent_tool_call_id: str = "",
    ) -> str:
        return await invoke_browser_inspect(
            self,
            caller_id,
            url=url,
            prompt=prompt,
            max_steps=max_steps,
            parent_message_id=parent_message_id,
            parent_tool_call_id=parent_tool_call_id,
        )

    async def resolve(self, message_id: str, response: dict) -> None:
        """解决待处理的权限请求。"""
        await resolve(self, message_id, response)

    async def _ask_guard(self, check, interrupt_event: asyncio.Event) -> bool:
        return await ask_guard(self, check, interrupt_event)

    async def _ask_user_input(
        self,
        payload: dict,
        interrupt_event: asyncio.Event,
        *,
        session_id: str,
        turn_id: str,
        message_id: str,
        tool_call_id: str,
    ) -> dict:
        return await ask_user_input(
            self,
            payload,
            interrupt_event,
            session_id=session_id,
            turn_id=turn_id,
            message_id=message_id,
            tool_call_id=tool_call_id,
        )

    async def _emit_error_message(
        self,
        *,
        session_id: str,
        turn_id: str,
        error: str,
    ) -> Message:
        return await emit_error_message(
            self._hooks,
            session_id=session_id,
            turn_id=turn_id,
            error=error,
        )

    async def _finish_partial_streaming_message(self, *, session_id: str) -> None:
        await finish_partial_streaming_message(
            self._hooks,
            self.current_message_for_session(session_id),
            session_id=session_id,
        )

    async def interrupt(self, session_id: str | None = None) -> bool:
        """中断运行中的 Session。

        只设置中断标志，不等待主循环退出。主循环的 finally
        块会异步完成清理。调用方不应假设调用返回后状态已归位。
        """
        if session_id is None:
            if self._running_session_id:
                session_id = self._running_session_id
            elif len(self._runs) == 1:
                session_id = next(iter(self._runs))
        if not session_id:
            return False
        run = self._runs.get(session_id)
        if run is None:
            return False
        run.interrupt_event.set()
        if run.task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await run.task
        return True

    # ═══════════════════════════════════════════════════════
    # 主循环（对标 Rust execute_turn）
    # ═══════════════════════════════════════════════════════

    async def _execute_turn(
        self,
        entry: RuntimeSession,
        question: str,
        max_steps: int,
        shadow_repo=None,
        *,
        top_level: bool = True,
    ) -> str:
        """主循环 — 拥有 messages 和 errors 的完整所有权。

        对标 Rust AgentRuntime::execute_turn()。
        """
        return await execute_turn(
            self,
            entry,
            question,
            max_steps,
            shadow_repo,
            top_level=top_level,
        )

    # ── 内部辅助 ────────────────────────────────────────

    def _resolve_id(self, prefix_or_id: str) -> str | None:
        """根据前缀匹配完整 session ID。"""
        # 精确匹配
        if prefix_or_id in self._sessions:
            return prefix_or_id
        # 前缀匹配
        matches = [sid for sid in self._sessions if sid.startswith(prefix_or_id)]
        if len(matches) == 1:
            return matches[0]
        # 磁盘查找
        disk_ids = self._workspace.list_session_ids()
        disk_matches = [sid for sid in disk_ids if sid.startswith(prefix_or_id)]
        if len(disk_matches) == 1:
            return disk_matches[0]
        return None
