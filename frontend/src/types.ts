// ── SSE events (incoming from backend) ────────────────

export interface PlanItem {
    description: string;
    state: string;
}

export type SSEEvent =
    | { type: "step_start"; step: number }
    | { type: "reasoning_token"; token: string }
    | { type: "thought_token"; token: string }
    | { type: "thought_end" }
    | {
          type: "tool_call_stream";
          index: number;
          name: string | null;
          args_len: number;
      }
    | { type: "tool_call"; tool: string; params?: Record<string, unknown> }
    | { type: "tool_result"; result: string }
    | { type: "plan_rewrite"; items?: PlanItem[] }
    | { type: "plan_advance"; state?: string; summary?: string }
    | { type: "subtask_start"; prompt?: string; max_steps?: number }
    | { type: "subtask_end"; result?: string }
    | { type: "terminal_chunk"; chunk: string }
    | { type: "finish"; answer: string }
    | { type: "error"; message: string };

// ── Tool display events (stored in Step.events) ────────

export type ToolEvent =
    | { type: "terminal_stream"; output: string }
    | { type: "tool_stream"; name: string; argsLen: number }
    | { type: "tool_call"; tool: string; params?: Record<string, unknown> }
    | { type: "tool_result"; result: string; expanded?: boolean }
    | { type: "plan_rewrite"; items?: PlanItem[] }
    | { type: "plan_advance"; state?: string; summary?: string }
    | { type: "subtask_start"; prompt?: string }
    | { type: "subtask_end"; result?: string }
    | { type: "error"; message: string };

// ── Step ──────────────────────────────────────────────

export interface Step {
    step: number;
    msgIndex: number;
    reasoning: string;
    action: string;
    events: ToolEvent[];
    open: boolean;
    actionFinal?: boolean;
}

// ── Message bubble ────────────────────────────────────

export interface Message {
    role: "user" | "assistant";
    content: string;
}

// ── Session cache ─────────────────────────────────────

export interface SessionInfo {
    session_id: string;
    session_name?: string;
    workspace: string;
    created_at?: string;
    updated_at?: string;
}

export interface CacheEntry {
    steps: Step[];
    answer: string | null;
    messages: Message[];
    _stepCounter?: number;
    _complete?: boolean;
}

export type SessionCache = Record<string, CacheEntry>;
