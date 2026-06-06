"""AgentRuntime — 多 Session 管理 + Hook 注入 + ReAct 主循环。

── 设计原则 ──
- 对标 Rust runtime.rs: AgentRuntime 是中央编排器
- 主循环拥有 messages 和 errors 的完整所有权
- Hook 只收通知（metrics, logging, SSE），抛异常不影响主循环
- 一次只允许一个 Session 处于 RUNNING 状态

── 对标 ──
- Rust: byte_e2e_agent_rs/src/core/runtime.rs
- 替代: agent/scheduler.py (Scheduler)
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid as _uuid

from agent.core.config import SessionConfig
from agent.core.workspace import Workspace
from agent.runtime.driver import execute_turn
from agent.runtime.messages import (
    emit_error_message,
    finish_partial_streaming_message,
)
from agent.runtime.pending import ask_guard, ask_user_input, resolve
from agent.runtime.subagents import invoke_agent, invoke_subagent
from agent.session.entry import SessionEntry
from agent.session.status import RuntimeStatus, SessionStatus
from shared.hooks import HookManager
from shared.types import Message

# ═══════════════════════════════════════════════════════════
# AgentRuntime
# ═══════════════════════════════════════════════════════════


class AgentRuntime:
    """Per-Project 执行运行时（对标 Rust AgentRuntime）。

    一次只允许一个 Session 在 RUNNING 状态。

    用法:
        ws = Workspace("/path/to/project", workspace_uuid="...")
        hooks = HookManager([StreamDriverHook(), LoggingHook()])
        runtime = AgentRuntime(ws, hooks)

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
        self._sessions: dict[str, SessionEntry] = {}
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
        if self._running_session_id:
            return RuntimeStatus.RUNNING
        return RuntimeStatus.IDLE

    @property
    def current_message(self) -> Message | None:
        """当前正在流式构建中的 Message（供 /recover 使用）。

        仅在 Agent 运行且 LLM 正在输出时非 None。
        """
        if self._streaming_holder is None:
            return None
        return self._streaming_holder[0]

    @property
    def pending_request(self) -> dict | None:
        """当前待处理的权限请求。"""
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
        ws: Workspace | None = None,
    ) -> SessionEntry:
        """创建新 Session。

        Args:
            config: Session 不可变配置
            session_id: 可选预定义 ID（不提供则自动生成）
            llm_client: LLM 客户端
            ws: Workspace 实例
        """
        sid = session_id or _uuid.uuid4().hex[:12]
        self._workspace.ensure_dirs(sid)
        self._workspace.save_session_config(sid, config)
        self._workspace.messages_path(sid).touch(exist_ok=True)

        # Write immutable prefix messages (KV-cache anchor) once at creation.
        from agent.session import write_session_prefix

        write_session_prefix(self._workspace, sid, config)

        entry = SessionEntry(
            id=sid,
            config=config,
            llm_client=llm_client,
            ws=ws or self._workspace,
        )
        self._sessions[sid] = entry
        return entry

    def get_session(self, session_id: str) -> SessionEntry | None:
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
        return self._running_session_id == session_id

    def _start_entry(
        self,
        entry: SessionEntry,
        question: str,
        *,
        max_steps: int = 50,
        shadow_repo=None,
    ) -> str:
        if self._running_session_id is not None:
            raise RuntimeError(f"Runtime already running session {self._running_session_id}")

        self._running_session_id = entry.id
        entry.transition_to(SessionStatus.RUNNING)
        self._interrupt_event = asyncio.Event()
        self._pending.clear()
        self._loop_task = asyncio.create_task(
            self._execute_turn(entry, question, max_steps, shadow_repo),
            name=f"runtime-{entry.id}",
        )
        return entry.id

    # ── Invoke: 用户 ────────────────────────────────────

    async def invoke_user(
        self,
        session: SessionEntry,
        question: str,
        *,
        max_steps: int = 50,
        shadow_repo=None,
    ) -> str:
        """用户发送消息，开始一个 Turn。

        对标 Rust AgentRuntime::invoke_user()。

        Args:
            session: SessionEntry
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
        session: SessionEntry,
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

    async def invoke_agent(
        self,
        caller_id: str,
        target_id: str,
        task: str,
        *,
        max_turns: int | None = None,
        parent_message_id: str = "",
        parent_tool_call_id: str = "",
    ) -> str:
        return await invoke_agent(
            self,
            caller_id,
            target_id,
            task,
            max_turns=max_turns,
            parent_message_id=parent_message_id,
            parent_tool_call_id=parent_tool_call_id,
        )

    async def invoke_subagent(
        self,
        caller_id: str,
        task: str,
        *,
        max_steps: int = 5,
        with_skills: list[str] | None = None,
        parent_message_id: str = "",
        parent_tool_call_id: str = "",
    ) -> str:
        return await invoke_subagent(
            self,
            caller_id,
            task,
            max_steps=max_steps,
            with_skills=with_skills,
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
            self.current_message,
            session_id=session_id,
        )

    async def interrupt(self) -> bool:
        """中断当前运行的 Session。

        设置中断标志后，等待主循环优雅退出（最多 5 秒），超时也返回 True。
        主循环的 finally 块会完成清理工作。
        """
        if self._interrupt_event is None:
            return False
        self._interrupt_event.set()
        task = self._loop_task
        if task is not None:
            with contextlib.suppress(TimeoutError, asyncio.CancelledError, Exception):
                await asyncio.wait_for(task, timeout=3.0)
        return True

    # ═══════════════════════════════════════════════════════
    # 主循环（对标 Rust execute_turn）
    # ═══════════════════════════════════════════════════════

    async def _execute_turn(
        self,
        entry: SessionEntry,
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
