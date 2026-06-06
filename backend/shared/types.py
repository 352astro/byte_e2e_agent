"""前后端透传的唯一类型体系 — Pydantic 定义。

── 设计原则 ──
1. Message 是唯一的数据容器：后端存储、前端渲染，结构完全相同。
2. 字段名即协议：StreamEvent.field 直接是 Message 的属性名，前端 msg[ev.field] += ev.delta。
3. 零 None，全零值。user/assistant/tool 一个 struct 搞定。
4. Pydantic 做边界校验（落盘/加载/API），流式阶段直接操作字段绕过校验。

── SSE 透传协议 ──
  后端 Message                       SSE StreamEvent                 前端 Message
  ────────────                       ──────────────                  ────────────
  content += "分析..."    ←──  field="content", delta="分析..."  ──→  content += "分析..."
  reasoning += "需要..."  ←──  field="reasoning", delta="需要..." ──→  reasoning += "需要..."
  tool_calls[idx].name += ←──  field="tool_calls", delta=...     ──→  tool_calls[idx].name += ...
  status = COMPLETE       ←──  kind="message_finish"             ──→  status = COMPLETE
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════


class MessageRole(str, Enum):
    """消息角色。USER/TOOL/SYSTEM 天然 COMPLETE，ASSISTANT 从 STREAMING 开始。"""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class MessageStatus(str, Enum):
    """消息构建状态。"""

    STREAMING = "streaming"
    COMPLETE = "complete"


class ToolExecutionStatus(str, Enum):
    """Semantic status for a completed tool result."""

    SUCCESS = "success"
    ERROR = "error"
    DENIED = "denied"
    TIMEOUT = "timeout"
    INTERRUPTED = "interrupted"


class StreamEventKind(str, Enum):
    """SSE 事件种类。"""

    MESSAGE_START = "message_start"
    CHUNK_DELTA = "chunk_delta"
    CHUNK_COMPLETE = "chunk_complete"
    MESSAGE_FINISH = "message_finish"
    TURN_COMPLETE = "turn_complete"
    INTERRUPTED = "interrupted"
    GUARD_REQUEST = "guard_request"
    RUNTIME_NOTICE = "runtime_notice"


# ═══════════════════════════════════════════════════════════
# ToolCall
# ═══════════════════════════════════════════════════════════


class ToolCallFunction(BaseModel):
    """OpenAI-format function 字段。"""

    name: str = ""
    arguments: str = ""  # JSON string


class ToolCall(BaseModel):
    """OpenAI-format tool call。"""

    id: str = ""
    type: str = "function"
    function: ToolCallFunction = Field(default_factory=ToolCallFunction)


# ═══════════════════════════════════════════════════════════
# Message — 前后端唯一的消息类型
# ═══════════════════════════════════════════════════════════


class Message(BaseModel):
    """贯穿流式缓冲 / 持久化 / 渲染的唯一消息类型。

    后端流式构建时直接 append 字段，完成后 model_dump() 落盘；
    前端收到 StreamEvent 后直接 msg[field] += delta 镜像构建。
    """

    id: str
    turn_id: str
    role: MessageRole = MessageRole.ASSISTANT
    status: MessageStatus = MessageStatus.STREAMING

    # ── 文本字段，流式时逐 token += ──
    content: str = ""
    reasoning: str = ""

    # ── 结构化字段 ──
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_result: str = ""  # tool 执行结果（role=TOOL 时用）

    # ── tool_result 的关联信息（role=TOOL 时用）──
    tool_call_id: str = ""  # 关联的 tool_call.id
    tool_name: str = ""  # 工具名
    tool_status: str = ToolExecutionStatus.SUCCESS.value
    tool_status_source: str = "tool"
    tool_status_reason: str = ""

    # ── 错误信息 ──
    error: str = ""

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    def mark_complete(self) -> None:
        self.status = MessageStatus.COMPLETE

    @classmethod
    def user_message(cls, id: str, turn_id: str, content: str) -> Message:
        """工厂：用户消息。"""
        return cls(
            id=id,
            turn_id=turn_id,
            role=MessageRole.USER,
            status=MessageStatus.COMPLETE,
            content=content,
        )

    @classmethod
    def assistant_message(cls, id: str, turn_id: str) -> Message:
        """工厂：assistant 消息（流式开始）。"""
        return cls(
            id=id,
            turn_id=turn_id,
            role=MessageRole.ASSISTANT,
            status=MessageStatus.STREAMING,
        )

    @classmethod
    def tool_message(
        cls,
        id: str,
        turn_id: str,
        tool_call_id: str,
        tool_name: str,
        result: str,
        tool_status: str = ToolExecutionStatus.SUCCESS.value,
        tool_status_source: str = "tool",
        tool_status_reason: str = "",
    ) -> Message:
        """工厂：工具执行结果消息。"""
        return cls(
            id=id,
            turn_id=turn_id,
            role=MessageRole.TOOL,
            status=MessageStatus.COMPLETE,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_result=result,
            tool_status=tool_status,
            tool_status_source=tool_status_source,
            tool_status_reason=tool_status_reason,
        )

    @classmethod
    def error_message(
        cls,
        id: str,
        turn_id: str,
        error: str,
    ) -> Message:
        """工厂：错误消息。"""
        return cls(
            id=id,
            turn_id=turn_id,
            role=MessageRole.ASSISTANT,
            status=MessageStatus.COMPLETE,
            error=error,
        )

    @classmethod
    def system_message(
        cls,
        id: str,
        turn_id: str,
        content: str,
    ) -> Message:
        """工厂：系统消息（append-only 上下文注入）。"""
        return cls(
            id=id,
            turn_id=turn_id,
            role=MessageRole.SYSTEM,
            status=MessageStatus.COMPLETE,
            content=content,
        )


# ═══════════════════════════════════════════════════════════
# StreamEvent — SSE 旁路传输协议
# ═══════════════════════════════════════════════════════════


class StreamEvent(BaseModel):
    """SSE 事件，从 StreamDriver Hook 推送到前端。

    field 直接是 Message 的属性名，前端 msg[field] += delta 镜像构建。
    """

    kind: StreamEventKind
    session_id: str = ""
    message_id: str = ""
    turn_id: str = ""

    # ── message 角色 ──
    role: str = ""  # "user" | "assistant" | "tool"

    # ── chunk_delta 专用 ──
    field: str = ""  # Message 属性名: "content" | "reasoning" | "tool_calls"
    delta: str = ""  # 增量文本
    tool_index: int = -1  # tool_calls 流式时的 tool 序号
    sub_field: str = ""  # "name" | "args" | ""  — tool_calls 的子字段

    # ── chunk_complete 专用 ──
    full_content: str = ""

    # ── 元数据 ──
    tool_name: str = ""
    tool_args: str = ""
    is_error: bool = False
    tool_status: str = ""
    tool_status_source: str = ""
    tool_status_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    usage: dict = Field(default_factory=dict)
    reason: str = ""  # interrupted 时的原因
    notice_id: str = ""
    level: str = ""
    title: str = ""
    detail: str = ""
    progress: str = ""
    retry_after_ms: int = 0
    retry_at: int = 0
    ttl_ms: int = 0
    sticky: bool = False

    # ═══════════════════════════════════════════════════════
    # 工厂方法
    # ═══════════════════════════════════════════════════════

    @classmethod
    def message_start(
        cls,
        turn_id: str,
        message_id: str,
        role: str = "assistant",
        session_id: str = "",
    ) -> StreamEvent:
        return cls(
            kind=StreamEventKind.MESSAGE_START,
            session_id=session_id,
            message_id=message_id,
            turn_id=turn_id,
            role=role,
        )

    @classmethod
    def chunk_delta(
        cls,
        message_id: str,
        field: str,
        delta: str,
        tool_name: str = "",
        tool_index: int = -1,
        sub_field: str = "",
        session_id: str = "",
    ) -> StreamEvent:
        return cls(
            kind=StreamEventKind.CHUNK_DELTA,
            session_id=session_id,
            message_id=message_id,
            field=field,
            delta=delta,
            tool_name=tool_name,
            tool_index=tool_index,
            sub_field=sub_field,
        )

    @classmethod
    def chunk_complete(
        cls,
        message_id: str,
        field: str,
        full_content: str,
        tool_name: str = "",
        tool_args: str = "",
        is_error: bool = False,
        tool_status: str = "",
        tool_status_source: str = "",
        tool_status_reason: str = "",
        session_id: str = "",
    ) -> StreamEvent:
        return cls(
            kind=StreamEventKind.CHUNK_COMPLETE,
            session_id=session_id,
            message_id=message_id,
            field=field,
            full_content=full_content,
            tool_name=tool_name,
            tool_args=tool_args,
            is_error=is_error,
            tool_status=tool_status,
            tool_status_source=tool_status_source,
            tool_status_reason=tool_status_reason,
        )

    @classmethod
    def message_finish(
        cls, message_id: str, session_id: str = "", usage: dict | None = None
    ) -> StreamEvent:
        return cls(
            kind=StreamEventKind.MESSAGE_FINISH,
            session_id=session_id,
            message_id=message_id,
            usage=usage or {},
            input_tokens=(usage or {}).get("prompt_tokens", 0),
            output_tokens=(usage or {}).get("completion_tokens", 0),
        )

    @classmethod
    def turn_complete(
        cls,
        turn_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        session_id: str = "",
    ) -> StreamEvent:
        return cls(
            kind=StreamEventKind.TURN_COMPLETE,
            session_id=session_id,
            turn_id=turn_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    @classmethod
    def interrupted(cls, reason: str, session_id: str = "") -> StreamEvent:
        return cls(
            kind=StreamEventKind.INTERRUPTED,
            session_id=session_id,
            reason=reason,
        )

    @classmethod
    def guard_request(
        cls,
        request_id: str,
        full_content: str,
        session_id: str = "",
    ) -> StreamEvent:
        return cls(
            kind=StreamEventKind.GUARD_REQUEST,
            session_id=session_id,
            message_id=request_id,
            field="guard_request",
            full_content=full_content,
        )

    @classmethod
    def runtime_notice(
        cls,
        notice_id: str,
        *,
        level: str = "info",
        title: str = "Runtime notice",
        detail: str = "",
        progress: str = "",
        retry_after_ms: int = 0,
        retry_at: int = 0,
        ttl_ms: int = 4500,
        sticky: bool = False,
        session_id: str = "",
        turn_id: str = "",
        message_id: str = "",
    ) -> StreamEvent:
        return cls(
            kind=StreamEventKind.RUNTIME_NOTICE,
            session_id=session_id,
            turn_id=turn_id,
            message_id=message_id,
            notice_id=notice_id,
            level=level,
            title=title,
            detail=detail,
            progress=progress,
            retry_after_ms=retry_after_ms,
            retry_at=retry_at,
            ttl_ms=ttl_ms,
            sticky=sticky,
        )


# ═══════════════════════════════════════════════════════════
# Turn — 一次用户交互的元数据
# ═══════════════════════════════════════════════════════════


class Turn(BaseModel):
    """Turn 元数据。Message 通过 turn_id 反向引用。"""

    id: str
    session_id: str = ""
    model_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    created_at: str = ""
