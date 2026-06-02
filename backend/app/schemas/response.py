"""Response models for FastAPI routes — exposes Message/StreamEvent/ToolCall
schemas in /openapi.json for frontend TypeScript auto-generation."""

from pydantic import BaseModel

from shared.types import (  # noqa: F401
    Message,
    MessageRole,
    MessageStatus,
    StreamEvent,
    StreamEventKind,
    ToolCall,
    ToolCallFunction,
)

# ── REST response models ──────────────────────────────


class CreateSessionResponse(BaseModel):
    session_id: str
    workspace: str


class ListSessionsResponse(BaseModel):
    workspace: str
    sessions: list[dict]


class SessionInfo(BaseModel):
    session_id: str
    workspace: str


class HistoryResponse(BaseModel):
    session: dict
    history: list[Message]


class RecoverResponse(BaseModel):
    session: dict
    messages: list[Message]
    session_running: bool = False
    runtime_busy: bool = False
    current_message: Message | None = None


class SessionStatusResponse(BaseModel):
    session_running: bool
    runtime_busy: bool


class RuntimeStatusResponse(BaseModel):
    runtime_busy: bool


class CommitInfo(BaseModel):
    sha: str
    short_sha: str
    message: str
    author_time: int


class CommitDetail(CommitInfo):
    files: list[str]


class CommitsResponse(BaseModel):
    commits: list[CommitInfo]


class WorkspaceRestoreResponse(BaseModel):
    ok: bool
    commit_sha: str


class MessageTruncateResponse(BaseModel):
    ok: bool
    message_id: str
    removed: int = 0
    deleted_subagents: int = 0


class InterruptResponse(BaseModel):
    ok: bool


# ── SSE event schema (for OpenAPI doc gen, not actual REST) ─


class StreamEventSchema(BaseModel):
    """SSE event structure — documented for frontend gen, served via SSE not REST."""

    kind: StreamEventKind
    session_id: str = ""
    message_id: str = ""
    turn_id: str = ""
    field: str = ""  # "content" | "reasoning" | "tool_calls"
    delta: str = ""
    full_content: str = ""
    tool_name: str = ""
    tool_args: str = ""
    is_error: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    reason: str = ""
