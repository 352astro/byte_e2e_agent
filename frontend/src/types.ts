// ═══════════════════════════════════════════════════════════
// 前后端透传类型 — 自动生成部分从 types.generated.ts 导入
// ═══════════════════════════════════════════════════════════

// ── Auto-generated (from backend /openapi.json via openapi-typescript) ──

import type { components } from "./types.generated";

export type { paths, operations } from "./types.generated";

// 从 generated 提取常用类型别名
export type Message = components["schemas"]["Message"];
export type ToolCall = components["schemas"]["ToolCall"];
export type ToolCallFunction = components["schemas"]["ToolCallFunction"];
export type MessageRole = components["schemas"]["MessageRole"];
export type MessageStatus = components["schemas"]["MessageStatus"];
export type StreamEventKind = components["schemas"]["StreamEventKind"];
export type CreateSessionRequest =
  components["schemas"]["CreateSessionRequest"];
export type SessionSettings = components["schemas"]["SessionSettings"];
export type SessionRule = components["schemas"]["SessionRule"];
export type SkillInfoResponse = components["schemas"]["SkillInfoResponse"];
export type ToolInfoResponse = components["schemas"]["ToolInfoResponse"];
export type ToolPresetResponse = components["schemas"]["ToolPresetResponse"];
export type ToolPresetListResponse =
  components["schemas"]["ToolPresetListResponse"];
export type ToolSetPreset = components["schemas"]["ToolSetPreset"];

// ── StreamEvent（SSE 协议，手写保持与 shared/types.py 一致）──

export interface StreamEvent {
  kind: StreamEventKind;
  session_id: string;
  message_id: string;
  turn_id: string;
  role: string; // "user" | "assistant" | "tool"
  field: string; // "content" | "reasoning" | "tool_calls"
  delta: string;
  tool_index: number; // tool_calls 流式时的 tool 序号
  sub_field: string; // "name" | "args" | ""  — tool_calls 的子字段
  full_content: string;
  tool_name: string;
  tool_args: string;
  is_error: boolean;
  tool_status: string;
  tool_status_source: string;
  tool_status_reason: string;
  input_tokens: number;
  output_tokens: number;
  usage?: Record<string, unknown>;
  reason: string;
}

// ── 前端专用类型 ──────────────────────────────────────

export interface SessionInfo {
  session_id: string;
  workspace: string;
  session_name?: string;
  session_kind?: "user" | "subagent" | string;
  parent_session_id?: string;
  parent_message_id?: string;
  parent_tool_call_id?: string;
}

export interface SessionCache {
  [sessionId: string]: {
    messages: Message[];
    _complete: boolean;
  };
}

export interface RecoverData {
  session: Record<string, unknown>;
  messages: Message[];
  session_running: boolean;
  runtime_busy: boolean;
  current_message?: Message | null;
  pending_request?: GuardPendingRequest | null;
}

export interface GuardRequest {
  kind?: string;
  request_id: string;
  action_type: string;
  subject: string;
  payload: Record<string, unknown>;
  title?: string;
  description?: string;
  choices?: Array<{
    id: string;
    label: string;
    description?: string;
  }>;
  questions?: Array<{
    id: string;
    label: string;
    type?: "text" | "textarea" | string;
    required?: boolean;
    placeholder?: string;
  }>;
  allow_custom?: boolean;
  choice_required?: boolean;
  multiple?: boolean;
  turn_id?: string;
  message_id?: string;
  tool_call_id?: string;
}

export interface GuardPendingRequest {
  message_id: string;
  kind: string;
  message: GuardRequest;
}

// ── Commit ──────────────────────────────────────────────

export interface CommitInfo {
  sha: string;
  short_sha: string;
  message: string;
  author_time: number;
}

export interface WorkspaceRestoreRequest {
  commit_sha: string;
  set_head?: boolean;
}

export interface WorkspaceRestoreResponse {
  ok: boolean;
  commit_sha: string;
}

export interface MessageTruncateRequest {
  message_id: string;
  keep?: boolean;
}

export interface MessageTruncateResponse {
  ok: boolean;
  message_id: string;
  removed: number;
  deleted_subagents?: number;
}

// ── Tool pair（前端渲染辅助）───────────────────────────

export interface ToolPair {
  callMessageId: string;
  callIndex: number;
  toolCall: ToolCall;
  resultMessage?: Message;
}
