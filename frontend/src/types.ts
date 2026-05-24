// ── Transcript (v2 streaming format) ──────────────────

export interface Transcript {
    id: string; // transcript_id — unique across session
    kind: string; // user_question | assistant | tool_result | permission_request | ...
    message: Record<string, unknown>;
}

export interface RecoverResponse {
    transcripts: Transcript[];
    buffered: Record<string, string>;
    running: boolean;
}

// ── SSE stream events (from GET /api/stream/{uuid}) ────

export type StreamEvent =
    | { event: "chunk"; transcript_id: string; text: string }
    | {
          event: "flush";
          transcript_id: string;
          kind: string;
          message: Record<string, unknown>;
      };

// ── Display items (what the UI renders) ────────────────

export interface DisplayTranscript {
    id: string;
    kind: string;
    message: Record<string, unknown>;
    pendingChunks: string; // accumulated chunk text before flush
    isFlushed: boolean;
}

// ── Session info ──────────────────────────────────────

export interface SessionInfo {
    session_id: string;
    session_name?: string;
    workspace: string;
    created_at?: string;
    updated_at?: string;
}

// ── Session cache ─────────────────────────────────────

export interface CacheEntry {
    transcripts: DisplayTranscript[];
    answer: string | null;
    _complete?: boolean;
}

export type SessionCache = Record<string, CacheEntry>;
