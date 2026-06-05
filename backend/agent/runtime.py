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
import json
import logging
import uuid as _uuid
from datetime import datetime, timezone

from agent.actions import (
    model_call,
)
from agent.core.config import SessionConfig, ToolSetPreset
from agent.core.prompts import SYSTEM_PROMPT
from agent.core.workspace import Workspace
from agent.errors import InterruptedError
from agent.session.entry import SessionEntry
from agent.session.status import RuntimeStatus, SessionStatus
from agent.tools import tool_registry
from agent.tools.shell import get_platform_hint
from agent.tools.skill import skill_context_message
from agent.tools.task import task_context_message
from agent.tools.toolset import ToolSet
from agent.tool_execution import execute_tool_calls
from app.core.config import TMP_DIR
from shared.hooks import BaseHook, GuardCheck, HookManager
from shared.types import Message

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# AgentRuntime
# ═══════════════════════════════════════════════════════════


class AgentRuntime:
    """Per-Project 执行运行时（对标 Rust AgentRuntime）。

    一次只允许一个 Session 在 RUNNING 状态。

    用法:
        ws = Workspace("/path/to/project")
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
        self._workspace = workspace or Workspace()
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

        entry = SessionEntry(
            id=sid,
            config=config,
            llm_client=llm_client,
            ws=ws or Workspace(str(self._workspace.root)),
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
        if self._running_session_id is not None:
            raise RuntimeError(
                f"Runtime already running session {self._running_session_id}"
            )

        entry = session
        self._running_session_id = entry.id
        entry.transition_to(SessionStatus.RUNNING)
        self._interrupt_event = asyncio.Event()
        self._pending.clear()

        # 启动主循环
        self._loop_task = asyncio.create_task(
            self._execute_turn(entry, question, max_steps, shadow_repo),
            name=f"runtime-{entry.id}",
        )

        return entry.id

    def start(
        self,
        session: SessionEntry,
        question: str,
        *,
        max_steps: int = 50,
        shadow_repo=None,
    ) -> str:
        """同步启动（fire-and-forget），供同步上下文使用。"""
        if self._running_session_id is not None:
            raise RuntimeError(
                f"Runtime already running session {self._running_session_id}"
            )
        session_id = _entry_id(session)
        self._loop_task = asyncio.create_task(
            self.invoke_user(
                session, question, max_steps=max_steps, shadow_repo=shadow_repo
            ),
            name=f"runtime-start-{session_id}",
        )
        return session_id

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
        """Agent 调用另一个 Agent Session。

        对标 Rust AgentRuntime::invoke_agent()。
        调用方进入 PENDING，目标执行完成后返回。

        Args:
            caller_id: 调用方 session ID
            target_id: 目标 session ID（支持前缀匹配）
            task: 任务描述
            max_turns: 最大 ReAct 轮次

        Returns:
            目标 Session 的响应文本
        """
        # 解析 target_id 前缀
        resolved = self._resolve_id(target_id)
        if resolved is None:
            return f"Error: target session '{target_id}' not found"

        target = self._sessions.get(resolved)
        if target is None:
            return f"Error: session '{resolved}' not active"

        # 权限检查
        if not target.config.access.can_invoke(caller_id):
            return (
                f"Error: session '{resolved}' does not allow invoke from '{caller_id}'"
            )

        # 调用方进入 PENDING
        caller_entry = self._sessions.get(caller_id)
        if caller_entry:
            caller_entry.transition_to(SessionStatus.PENDING)

        created_interrupt_event = False
        if self._interrupt_event is None:
            self._interrupt_event = asyncio.Event()
            created_interrupt_event = True
        previous_running = self._running_session_id
        try:
            await self._hooks.on_subagent_start(
                task=task,
                parent_session_id=caller_id,
                child_session_id=target.id,
                parent_message_id=parent_message_id,
                parent_tool_call_id=parent_tool_call_id,
                max_steps=max_turns or 10,
            )
            self._running_session_id = target.id
            target.transition_to(SessionStatus.RUNNING)
            result = await self._execute_turn(
                target,
                task,
                max_turns or 10,
                top_level=False,
            )
            self._running_session_id = previous_running
            await self._hooks.on_subagent_end(
                result=result,
                parent_session_id=caller_id,
                child_session_id=target.id,
                parent_message_id=parent_message_id,
                parent_tool_call_id=parent_tool_call_id,
            )
            return result
        finally:
            self._running_session_id = previous_running
            if created_interrupt_event:
                self._interrupt_event = None
            if target.status == SessionStatus.RUNNING:
                target.transition_to(SessionStatus.IDLE)
            if caller_entry:
                caller_entry.transition_to(SessionStatus.RUNNING)

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
        """Create an ephemeral child session and invoke it from caller_id."""
        openai_client, model_id = self._get_llm()
        child_id = f"{caller_id}-sub-{_uuid.uuid4().hex[:8]}"
        preamble = _build_subagent_preamble(with_skills or [])
        child_tools = [
            name
            for name in ToolSetPreset.ALL.tool_names()
            if name not in {"SubAgent", "BrowserInspect", "TaskList", "TaskRewrite"}
        ]
        config = SessionConfig(
            name=f"subagent:{caller_id}",
            model_id=model_id,
            preamble=preamble,
            tool_set_preset=ToolSetPreset.CUSTOM,
            custom_tools=child_tools,
            rules=[task],
            access=SessionConfig.subagent(
                parent_id=caller_id,
                name=f"subagent:{caller_id}",
                task=task,
                model_id=model_id,
            ).access,
        )
        self.create_session(
            config,
            session_id=child_id,
            llm_client=openai_client,
            ws=Workspace(str(self._workspace.root)),
        )
        _write_subagent_metadata(
            self._workspace,
            child_id,
            parent_id=caller_id,
            parent_message_id=parent_message_id,
            parent_tool_call_id=parent_tool_call_id,
            task=task,
        )
        result = await self.invoke_agent(
            caller_id,
            child_id,
            task,
            max_turns=max_steps,
            parent_message_id=parent_message_id,
            parent_tool_call_id=parent_tool_call_id,
        )
        return f"SubAgent session {child_id} completed.\n\n{result}"

    async def resolve(self, message_id: str, response: dict) -> None:
        """解决待处理的权限请求。"""
        pending = self._pending.get(message_id)
        if pending is None:
            raise KeyError(f"No pending request: {message_id}")
        pending["response"] = response
        pending["event"].set()

    async def _ask_guard(
        self, check: GuardCheck, interrupt_event: asyncio.Event
    ) -> bool:
        request_id = _uuid.uuid4().hex
        event = asyncio.Event()
        self._pending[request_id] = {
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
            await self._hooks.on_guard_request(request_id=request_id, check=check)
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
            response = self._pending.get(request_id, {}).get("response", {})
            return bool(response.get("allow") or response.get("approved"))
        finally:
            self._pending.pop(request_id, None)

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
        self._pending[request_id] = {
            "kind": "user_input_request",
            "message": message,
            "event": event,
        }
        entry = self._sessions.get(session_id)
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
            await self._hooks.on_guard_request(request_id=request_id, check=check)
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
            return self._pending.get(request_id, {}).get("response", {})
        finally:
            self._pending.pop(request_id, None)
            if entry and entry.status == SessionStatus.PENDING:
                entry.transition_to(SessionStatus.RUNNING)

    async def _emit_error_message(
        self,
        *,
        session_id: str,
        turn_id: str,
        error: str,
    ) -> Message:
        msg = Message.error_message(_uuid.uuid4().hex, turn_id, error)
        await self._hooks.on_message_start(msg=msg, session_id=session_id)
        await self._hooks.on_chunk_complete(
            msg=msg,
            field="error",
            full_content=msg.error,
            is_error=True,
            session_id=session_id,
        )
        await self._hooks.on_message_finish(msg=msg, session_id=session_id)
        return msg

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
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                pass
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
        openai_client, default_model_id = self._get_llm()
        model_id = entry.config.model_id or default_model_id
        sid = entry.id
        ws = entry.ws
        intr = self._interrupt_event
        assert intr is not None

        turn_id = _uuid.uuid4().hex
        final_answer = ""

        # ── on_turn_start ──────────────────────────────
        await self._hooks.on_turn_start(
            turn_id=turn_id,
            session_id=sid,
            user_question=question,
        )

        try:
            total_input_tokens = 0
            total_output_tokens = 0

            # 用户消息 — 构建 Message 并完整流式传输
            user_id = _uuid.uuid4().hex
            user_msg = Message.user_message(user_id, turn_id, question)
            await self._hooks.on_message_start(msg=user_msg, session_id=sid)
            await self._hooks.on_chunk_delta(
                msg=user_msg, field="content", delta=question, session_id=sid
            )
            await self._hooks.on_chunk_complete(
                msg=user_msg, field="content", full_content=question, session_id=sid
            )
            await self._hooks.on_message_finish(msg=user_msg, session_id=sid)
            await asyncio.sleep(0)

            # 收集 Hook 注入的上下文（长期记忆 / RAG 等）— 仅一次
            injected_context = await self._hooks.gather_context(
                turn_id=turn_id,
                session_id=sid,
                user_question=question,
            )

            for step in range(max_steps):
                if intr.is_set():
                    raise InterruptedError("Interrupted by user")

                # 构建消息列表（主循环拥有）
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
                    task_context_message(ws, session_id=sid),
                ]
                preloaded_skill_context = _build_preloaded_skills_context(
                    entry.config.preloaded_skills
                )
                if preloaded_skill_context:
                    messages.append(
                        {"role": "system", "content": preloaded_skill_context}
                    )
                if entry.config.preamble:
                    messages.append(
                        {"role": "system", "content": entry.config.preamble}
                    )
                if entry.config.rules:
                    messages.append(
                        {
                            "role": "system",
                            "content": "## Session Rules\n"
                            + "\n".join(f"- {rule}" for rule in entry.config.rules),
                        }
                    )
                # 附加 Session 中的 LLM 上下文
                from agent.session import load_session

                session = load_session(str(ws.root), sid, ws=ws)
                messages.extend(session.get_llm_context())

                # 注入 Hook 上下文（已在上方 gather 一次，复用）
                if injected_context:
                    messages.extend(injected_context)

                assistant_id = _uuid.uuid4().hex
                tool_names = entry.config.tool_names()
                toolset = (
                    ToolSet(tool_registry, *tool_names)
                    if tool_names
                    else _default_toolset()
                )

                # ── model_call ─────────────────────────
                # model_call 内部已处理 on_message_start / on_message_finish
                streaming_holder: list[Message | None] = [None]
                self._streaming_holder = streaming_holder
                assistant_msg, finish_reason = await model_call(
                    openai_client,
                    model_id,
                    sid,
                    messages,
                    toolset.openai_tools,
                    message_id=assistant_id,
                    turn_id=turn_id,
                    interrupt_event=intr,
                    hook_manager=self._hooks,
                    streaming_holder=streaming_holder,
                )
                self._streaming_holder = None

                has_tool_calls = assistant_msg.has_tool_calls
                if assistant_msg.content:
                    final_answer = assistant_msg.content

                # ── 累计 token ──────────────────────────
                usage = _extract_usage(assistant_msg)
                total_input_tokens += usage.get("prompt_tokens", 0)
                total_output_tokens += usage.get("completion_tokens", 0)

                if finish_reason == "stop":
                    break

                if not has_tool_calls:
                    await self._emit_error_message(
                        session_id=sid,
                        turn_id=turn_id,
                        error="LLM returned no tool_calls and no content.",
                    )
                    break

                async def invoke_child_agent(
                    prompt,
                    max_steps=5,
                    with_skills=None,
                    tool_call_id="",
                ):
                    return await self.invoke_subagent(
                        sid,
                        prompt,
                        max_steps=max_steps,
                        with_skills=with_skills,
                        parent_message_id=assistant_msg.id,
                        parent_tool_call_id=tool_call_id,
                    )

                async def request_human_input(
                    payload,
                    interrupt_event=None,
                    tool_call_id="",
                ):
                    return await self._ask_user_input(
                        payload,
                        interrupt_event or intr,
                        session_id=sid,
                        turn_id=turn_id,
                        message_id=assistant_msg.id,
                        tool_call_id=tool_call_id,
                    )

                await execute_tool_calls(
                    assistant_msg=assistant_msg,
                    ws=ws,
                    toolset=toolset,
                    interrupt_event=intr,
                    openai_client=openai_client,
                    model_id=model_id,
                    session_id=sid,
                    turn_id=turn_id,
                    hook_manager=self._hooks,
                    ask_guard=self._ask_guard,
                    invoke_subagent=invoke_child_agent,
                    request_human_input=request_human_input,
                )

        except InterruptedError:
            error_msg_obj = await self._emit_error_message(
                session_id=sid,
                turn_id=turn_id,
                error=(
                    "The user interrupted the agent before it could "
                    "finish. Summarize what you have done so far and ask "
                    "how to proceed."
                ),
            )
            final_answer = error_msg_obj.error
        except Exception as exc:
            logger.warning(
                "AgentRuntime: turn failed with %s: %s",
                type(exc).__name__,
                exc,
            )
            error_msg_obj = await self._emit_error_message(
                session_id=sid,
                turn_id=turn_id,
                error=str(exc),
            )
            final_answer = error_msg_obj.error
        finally:
            # ── on_turn_end ───────────────────────────
            await self._hooks.on_turn_end(
                turn_id=turn_id,
                session_id=sid,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
            )
            await self._hooks.flush()

            # 清理
            self._streaming_holder = None
            if top_level:
                self._running_session_id = None
                self._loop_task = None
            entry.transition_to(SessionStatus.IDLE)
        return final_answer or "SubAgent completed (no output)."

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


# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════


def _default_toolset() -> ToolSet:
    from agent.tools import tool_registry

    return ToolSet(tool_registry)


def _entry_id(entry: SessionEntry) -> str:
    value = getattr(entry, "id", "")
    if isinstance(value, str) and value:
        return value
    legacy_value = getattr(entry, "session_id", "")
    if isinstance(legacy_value, str) and legacy_value:
        return legacy_value
    return str(value)


def _write_subagent_metadata(
    workspace: Workspace,
    session_id: str,
    *,
    parent_id: str,
    parent_message_id: str,
    parent_tool_call_id: str,
    task: str,
) -> None:
    path = workspace.session_dir(session_id) / "session.json"
    now = datetime.now(timezone.utc).isoformat()
    existing = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    payload = {
        **existing,
        "session_id": session_id,
        "workspace": str(workspace.root),
        "session_kind": "subagent",
        "parent_session_id": parent_id,
        "parent_message_id": parent_message_id,
        "parent_tool_call_id": parent_tool_call_id,
        "task": task,
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _extract_usage(msg: Message | None) -> dict:
    """从 Message 中提取 usage 信息。"""
    if msg is None:
        return {}
    usage = getattr(msg, "_usage", None)
    if usage:
        return usage
    # 估算
    result = {}
    if msg.content:
        result["completion_tokens"] = len(msg.content) // 4
    return result


def _build_subagent_preamble(with_skills: list[str]) -> str:
    parts = [
        (
            "You are a sub-agent. Complete the assigned task and return a final "
            "answer. You have an independent session and do not inherit the "
            "parent conversation; rely only on the task and your own tool results."
        )
    ]
    skill_context = _build_preloaded_skills_context(with_skills)
    if skill_context:
        parts.append(skill_context)
    return "\n\n".join(parts)


def _build_preloaded_skills_context(with_skills: list[str]) -> str:
    if not with_skills:
        return ""

    from agent.tools.skill import get_skill

    parts: list[str] = []
    for skill_name in with_skills:
        skill = get_skill(skill_name)
        if skill is None:
            continue
        parts.append(
            f"[SKILL: {skill_name}]\n\n"
            "The following skill methodology is pre-loaded into your context. "
            "Follow it exactly.\n\n"
            f"{skill.read()}"
        )
    return "\n\n".join(parts)
