# Session Metadata, Access Control, and Subagent Rendering Plan

## Background

The runtime now supports invoke-style subagents as independent sessions:

- A parent user session invokes a child session.
- The parent goes `RUNNING -> PENDING -> RUNNING`.
- The child goes `IDLE -> RUNNING -> IDLE`.
- Child messages are persisted under the child session id.
- SSE events carry `session_id` and are routed to matching subscribers.

However, the API still exposes too little session metadata. The frontend cannot reliably tell a user-invokable session from a subagent session, and backend user entrypoints do not enforce `AccessPolicy`. As a result, any session id with a `messages.jsonl` file can currently be selected and sent to like a normal user session.

## Goals

- Expose enough session metadata for the frontend to render different session kinds correctly.
- Enforce backend access rules so user-initiated chat cannot target private/ephemeral subagent sessions.
- Make subagent transcript rendering reuse the existing chat/message code without giving users direct send controls.
- Keep invoke result flow explicit: parent tool result links to a child session in structured data, not by parsing text.
- Preserve current user session behavior.

## Non-goals

- Do not implement durable recovery of an in-flight invoke stack after server restart in this phase.
- Do not allow users to send messages directly into subagent sessions.
- Do not implement parallel subagent execution yet.
- Do not delete child session messages immediately on completion; the frontend needs them for transcript inspection.

## Current Problems

### 1. Session list metadata is insufficient

`GET /api/sessions` currently returns items like:

```json
{
  "session_id": "...",
  "workspace": "..."
}
```

This is not enough to distinguish:

- User-created sessions.
- Runtime-created subagent sessions.
- Persistent sessions.
- Ephemeral/TTL sessions.
- Sessions visible to the user but not user-invokable.
- Sessions currently running, pending, interrupted, or idle.

### 2. Session config is saved but not surfaced as typed metadata

`Workspace.save_session_config()` writes `config.json`, including `access.owner`, `visibility`, `invoke_permission`, and `lifecycle`. But `Project.list_sessions()` and `Project.get_info()` do not read and normalize this config.

### 3. Access is checked for agent-to-agent invoke, not user-to-session send

`AgentRuntime.invoke_agent()` checks:

```python
target.config.access.can_invoke(caller_id)
```

But user send goes through `Project.start_chat() -> scheduler.start()` and only checks that the session exists. It should reject sessions whose policy does not allow user invocation.

### 4. Parent tool result only contains child session id in text

Current parent result is a string:

```text
SubAgent session <child_id> completed.

<child final answer>
```

The frontend should not parse this. It needs structured metadata on the parent `tool_result` message.

### 5. Runtime status is memory-only

`SessionStatus.RUNNING/PENDING/IDLE/INTERRUPTED` lives in `SessionEntry`, not on disk. After server restart, all sessions are effectively not running unless a new runtime entry is recreated and started.

This is acceptable for now, but the API must label status as runtime-only and default to `idle/offline` for sessions loaded from disk.

## Proposed Backend Data Model

### Add typed session metadata

In `backend/app/schemas/response.py`, replace generic session dicts with a typed model:

```python
class SessionOwnerInfo(BaseModel):
    kind: str = "user"          # "user" | "session"
    session_id: str | None = None


class SessionAccessInfo(BaseModel):
    owner: SessionOwnerInfo
    visibility: str             # private | whitelist | public
    invoke_permission: str      # owner_only | whitelist | any_agent
    lifecycle: str              # persistent | ephemeral | ttl
    whitelist_ids: list[str] = []
    idle_turns: int = 5


class SessionInfo(BaseModel):
    session_id: str
    workspace: str
    name: str = ""
    kind: str                   # user | subagent
    parent_session_id: str | None = None
    root_session_id: str | None = None
    access: SessionAccessInfo
    user_visible: bool = False
    user_invokable: bool = False
    runtime_status: str = "idle"  # idle | running | pending | interrupted | offline
    running: bool = False
    created_at: float | None = None
    updated_at: float | None = None
```

`kind` should be derived conservatively:

- `access.owner.kind == "user"` -> `kind = "user"`.
- `access.owner.kind == "session"` -> `kind = "subagent"`, `parent_session_id = owner.session_id`.

`user_invokable` should be true only when:

- owner is user and invoke permission allows user, or
- a new explicit policy says user may invoke it.

Given current `AccessPolicy.can_invoke(None)` already treats `caller_id=None` as user:

```python
user_invokable = config.access.can_invoke(None)
```

For current defaults:

- User main session: `OWNER_ONLY` + owner user -> user invokable.
- Subagent session: owner session + whitelist parent -> not user invokable.

### Make CreateSessionResponse return SessionInfo

Current:

```python
class CreateSessionResponse(BaseModel):
    session_id: str
```

Recommended:

```python
class CreateSessionResponse(BaseModel):
    session: SessionInfo
```

Compatibility option:

```python
class CreateSessionResponse(BaseModel):
    session_id: str
    workspace: str = ""
    session: SessionInfo | None = None
```

Prefer compatibility option if frontend migration should be incremental.

### Make list/recover/history use typed SessionInfo

Update:

```python
class ListSessionsResponse(BaseModel):
    workspace: str
    sessions: list[SessionInfo]


class HistoryResponse(BaseModel):
    session: SessionInfo
    history: list[Message]


class RecoverResponse(BaseModel):
    session: SessionInfo
    messages: list[Message]
    running: bool = False
    current_message: Message | None = None
```

## Backend Implementation Plan

### Step 1. Add session metadata loading in Project

Add helpers to `backend/app/services/project.py`:

```python
def _session_info(self, session_id: str) -> dict[str, Any]:
    config_data = CoreWorkspace(self._workspace).load_session_config(session_id)
    config = normalize_config_or_default(session_id, config_data)
    access = normalize_access(config)
    entry = self.scheduler.get_session(session_id) if self._runtime else None
    runtime_status = entry.status.value if entry else "idle"
    messages_path = self._messages_path(session_id)
    return {
        "session_id": session_id,
        "workspace": self._workspace,
        "name": config.name or session_id,
        "kind": "subagent" if access.owner.kind == "session" else "user",
        "parent_session_id": access.owner.session_id if access.owner.kind == "session" else None,
        "root_session_id": ...,
        "access": ...,
        "user_visible": access.is_visible_to(None),
        "user_invokable": access.can_invoke(None),
        "runtime_status": runtime_status,
        "running": runtime_status == "running",
        "created_at": ...,
        "updated_at": messages_path.stat().st_mtime if messages_path.exists() else None,
    }
```

Important: `create_session()` currently only creates `messages.jsonl`; it does not save a config. Change it to create a real runtime-compatible user session config using `SessionConfig.user_main(...)` and save it through `Workspace.save_session_config()`. This prevents "config missing" fallback from becoming a permanent source of ambiguity.

### Step 2. Update Project API return values

- `Project.create_session()` should return full session info, plus legacy `session_id`.
- `Project.list_sessions()` should return `list[SessionInfo]`.
- `Project.get_info()` should return `SessionInfo`.
- `Project.get_recovery_state()` should return typed `session` metadata.

### Step 3. Enforce access on user send

Add this check in `Project.start_chat()` before subscribing and before `scheduler.start()`:

```python
info = self.get_info(session_id)
if not info["user_invokable"]:
    raise PermissionError(f"Session {session_id} is not user-invokable")
```

Then map it in `chat.py`:

```python
except PermissionError as exc:
    raise HTTPException(status_code=403, detail=str(exc))
```

Also check `entry.config.access.can_invoke(None)` after creating/reloading the `SessionEntry`. This protects against stale or malformed `SessionInfo`.

### Step 4. Enforce access on user-only mutating routes

Some operations should be user-session only:

- `/api/session/{sid}/chat`
- `/api/session/{sid}/messages/truncate`
- `/api/session/{sid}/workspace/restore`
- Possibly `/api/session/{sid}/commits`

For subagent sessions:

- `history`, `recover`, and `stream` may be readable if `user_visible` is true.
- `delete` should be allowed only through parent/session lifecycle rules or admin-like UI behavior. For now, hide subagent sessions from sidebar and avoid direct delete unless explicitly selected through parent transcript.

Add helpers:

```python
Project.assert_user_invokable(session_id)
Project.assert_user_visible(session_id)
Project.assert_user_mutable(session_id)
```

### Step 5. Make child session id structured in messages

Add structured metadata to `Message`.

Option A:

```python
class Message(BaseModel):
    ...
    metadata: dict[str, Any] = Field(default_factory=dict)
```

Then in parent tool result:

```python
tool_result_msg.metadata["child_session_id"] = child_id
tool_result_msg.metadata["child_kind"] = "subagent"
```

Option B: add specific fields:

```python
child_session_id: str = ""
parent_session_id: str = ""
```

Recommendation: use `metadata` because future tool-specific links will need the same mechanism.

### Step 6. Return structured subagent result from runtime

Current `execute_one_tool()` returns only a string. To attach metadata cleanly, introduce a small result type:

```python
@dataclass
class ToolExecutionResult:
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)
```

Then:

- Normal tools return `ToolExecutionResult(output=result_str)`.
- `SubAgent` returns `ToolExecutionResult(output=final_answer, metadata={"child_session_id": child_id})`.
- Runtime writes `output` to `tool_result`, and copies metadata to `Message.metadata`.

Incremental alternative: let `invoke_subagent()` return a JSON-like sentinel or tuple internally. Avoid exposing this in text.

### Step 7. Session config recovery

When `Project.start_chat()` or `get_stream()` sees a session on disk but no runtime entry:

- Load `config.json`.
- Reconstruct `SessionConfig`.
- Create `SessionEntry` with that config.

This matters for access enforcement after server restart. If config reconstruction is deferred, `Project.get_info()` still must enforce policy from raw config JSON.

### Step 8. Tests

Backend tests should cover:

- `GET /api/sessions` includes `kind`, `access`, `user_invokable`, `parent_session_id`.
- user-created session is `kind=user`, `user_invokable=true`.
- subagent session is `kind=subagent`, `parent_session_id=<parent>`, `user_invokable=false`.
- `POST /api/session/{subagent}/chat` returns `403`.
- `GET /api/session/{subagent}/recover` returns messages if visible.
- parent SubAgent tool result contains `metadata.child_session_id`.
- after runtime restart/rebuild, subagent is still not user-invokable.

## Frontend Rendering Plan

### Core rule

Use the same transcript renderer for parent and child sessions, but with different capabilities.

Split the current `AgentDemo` into:

```tsx
<SessionTranscript
  sessionId={sessionId}
  mode="interactive" | "readonly"
  compact={boolean}
  depth={number}
/>
```

`AgentDemo` becomes a composition:

```tsx
<SessionTranscript mode="interactive" sessionId={sessionId} />
<AgentInput ... />
<CommitGraphPanel ... />
```

Subagent tool result uses:

```tsx
<SubagentTranscript
  childSessionId={message.metadata.child_session_id}
  depth={depth + 1}
/>
```

### `useAgentStream` usage

`useAgentStream()` is already self-contained enough to be called multiple times:

- Parent calls `useAgentStream(parentSid)`.
- Child transcript calls `useAgentStream(childSid)`.

But child transcript must be read-only:

- Do not render `AgentInput`.
- Do not expose delete/replay message actions.
- Do not expose interrupt.
- Use `reloadMessages` and `/stream` only.

### Sidebar rendering

`SessionSidebar` should use metadata:

- Show only `kind === "user"` sessions by default.
- Hide `kind === "subagent"` from the main session list.
- Optional: add a "Show subagents" toggle for debugging.
- Use `name` as title, `session_id` as secondary id.
- Display runtime state:
  - `running`: active indicator.
  - `pending`: waiting indicator.
  - `idle`: neutral.
  - `interrupted`: warning.
- Disable selection/send affordances for `!user_invokable`.

### Tool card rendering

For `SubAgent` paired tool result:

- Header:
  - Tool name: `SubAgent`.
  - Child status: running / complete / interrupted if available.
  - Child session short id.
- Body:
  - First line: final answer summary from parent tool result.
  - Expandable section: child transcript.

Recommended UI:

```tsx
if (pair.toolCall.function.name === "SubAgent") {
  return (
    <SubagentToolCard
      pair={pair}
      childSessionId={pair.resultMessage?.metadata?.child_session_id}
      defaultCollapsed={false}
      depth={depth}
    />
  );
}
```

### Recursion guard

Nested transcripts should accept `depth`.

- `depth <= 2`: allow inline child transcript.
- `depth > 2`: render a compact link/button: "Open subagent session".

This prevents infinite UI expansion if subagents eventually invoke subagents.

### Recover behavior

Parent recover:

- Loads parent messages.
- Tool result includes `metadata.child_session_id`.
- Subagent transcript component mounts and independently calls child recover.

Child recover:

- Loads child messages.
- If child is currently running, subscribes to child stream.
- Does not show input.

### Access failures

If the user somehow selects a subagent session directly:

- `GET /recover` may work if visible.
- `POST /chat` should return `403`.
- Frontend should show read-only transcript with a small "Subagent session" label, not an input.

## Migration Order

1. Backend typed session metadata and access enforcement.
2. Add `Message.metadata`.
3. Return `child_session_id` as structured metadata.
4. Update frontend types.
5. Split `SessionTranscript` out of `AgentDemo`.
6. Hide subagent sessions from sidebar.
7. Render inline child transcript in `SubAgent` tool card.
8. Add tests.

## Risks and Design Notes

- `SessionStatus` is not durable. Do not pretend it survives restart.
- `Lifecycle.EPHEMERAL` currently means "created for a child task", not "delete immediately".
- `AccessPolicy.is_visible_to(None)` currently says private subagent sessions are not user-visible because owner is a session. For UI transcript inspection, we may need a separate concept: "visible through parent link". Do not make all subagents public.
- A good compromise: direct `/api/sessions` hides subagents, but `/api/session/{child}/recover?parent=<parent>` or an internal parent-linked check allows reading a child transcript if the child is owned by the parent session that appears in the parent message metadata.
- The parent-child link should be verified server-side eventually; the frontend should not be trusted just because it knows a child id.

## Prompt for Backend Agent

```text
You are working in /home/kongksora/code/byte_e2e_agent.

Implement backend session metadata and access enforcement for invoke-style subagents.

Requirements:
- Add typed session metadata models in backend/app/schemas/response.py.
- Project.list_sessions(), Project.get_info(), and Project.get_recovery_state() must return metadata that identifies user sessions vs subagent sessions.
- Metadata must include session_id, workspace, name, kind, parent_session_id, access, user_visible, user_invokable, runtime_status, running, created_at, updated_at.
- User-created sessions must save a SessionConfig.user_main config at creation time.
- User send through POST /api/session/{sid}/chat must reject non-user-invokable sessions with HTTP 403.
- Add helpers in Project for assert_user_visible/assert_user_invokable/assert_user_mutable.
- Do not allow user chat into subagent sessions.
- Preserve current normal user session behavior.
- Add tests for user session metadata, subagent metadata, and 403 on user chat to subagent.

Important context:
- AccessPolicy.can_invoke(None) represents user invocation.
- Subagent configs use owner=Owner.session(parent_id), lifecycle=EPHEMERAL.
- Runtime status is in-memory only; after restart default to idle/offline, but access must still be enforced from config.json.
- Do not revert unrelated changes.
```

## Prompt for Runtime/Message Agent

```text
You are working in /home/kongksora/code/byte_e2e_agent.

Add structured child session metadata to SubAgent tool results.

Requirements:
- Add Message.metadata: dict[str, Any] with default_factory=dict in backend/shared/types.py.
- Update frontend hand-written/generated types as needed.
- Introduce an internal ToolExecutionResult dataclass or equivalent so execute_one_tool can return output plus metadata.
- Normal tools should keep existing behavior.
- SubAgent execution should return metadata containing child_session_id and child kind.
- AgentRuntime must copy ToolExecutionResult.metadata into the parent tool_result Message.metadata.
- Avoid making frontend parse child_session_id from tool_result text.
- Preserve current SSE and persistence behavior.
- Add tests that parent SubAgent tool_result includes metadata.child_session_id.

Do not implement frontend rendering in this task.
```

## Prompt for Frontend Agent

```text
You are working in /home/kongksora/code/byte_e2e_agent.

Implement frontend rendering for user sessions and subagent sessions using the new session metadata and Message.metadata.child_session_id.

Requirements:
- Update frontend SessionInfo type to include backend metadata: kind, parent_session_id, access, user_visible, user_invokable, runtime_status, running.
- SessionSidebar must show user sessions by default and hide subagent sessions unless a debug/show-subagents toggle is enabled.
- Disable or hide interactive controls for sessions where user_invokable is false.
- Extract the message transcript portion of AgentDemo into a reusable SessionTranscript component.
- SessionTranscript should call useAgentStream(sessionId) and render messages using existing MessageCard/ToolPairCard logic.
- For mode="readonly", do not render AgentInput, interrupt, delete, replay, commit graph, or workspace restore controls.
- SubAgent tool result cards should render an inline readonly child SessionTranscript using resultMessage.metadata.child_session_id.
- Add recursion depth guard: inline render up to depth 2, then show a compact "Open subagent session" affordance.
- Do not parse child session id from text.
- Preserve existing parent chat UX.

Coordinate with backend metadata fields; if generated OpenAPI types are stale, update the handwritten frontend types conservatively.
```

