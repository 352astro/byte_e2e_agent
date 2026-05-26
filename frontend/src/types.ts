// ── Transcript ──────────────────────────────────────────

export interface Transcript {
    id: string;
    kind: string;
    message: Record<string, unknown>;
    commit_sha?: string; // non-empty when a shadow commit is attached
}

export interface RecoverResponse {
    transcripts: Transcript[];
    buffered: Record<string, string>;
    running: boolean;
}

// ── Sub-stream (chunk with kind/id) ──────────────────────

export interface SubStream {
    id: string; // sub-stream id
    kind: string; // thinking | response | tool_name | tool_arguments | tool_result
    text: string; // accumulated text for this sub-stream
}

// ── SSE stream events ───────────────────────────────────

export type StreamEvent =
    | {
          event: "chunk";
          transcript_id: string;
          id: string;
          kind: string;
          text: string;
      }
    | {
          event: "flush";
          transcript_id: string;
          kind: string;
          message: Record<string, unknown>;
          sub_streams: Array<{ id: string; kind: string; text: string }>;
          active_sub_stream: { id: string; kind: string; text: string } | null;
          commit_sha?: string;
      };

// ── Display items ────────────────────────────────────────

export interface DisplayTranscript {
    id: string;
    kind: string;
    message: Record<string, unknown>;
    subStreams: SubStream[]; // completed sub-streams, in order
    activeSubStream: SubStream | null; // currently streaming
    isFlushed: boolean;
    commitSha?: string; // shadow commit sha for user_question transcripts
}

// ── Tool call ↔ result pairing ───────────────────────────

export interface ToolPair {
    callTranscriptId: string;
    callIndex: number;
    toolCallId: string;
    toolName: string;
    arguments: string;
    result?: DisplayTranscript;
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
    _complete?: boolean;
}

export type SessionCache = Record<string, CacheEntry>;


// ── Shadow commit ────────────────────────────────────────

export interface CommitInfo {
    sha: string;
    short_sha: string;
    message: string;
    author_time: number;
    transcript_id: string | null;
}

export interface CommitDetail extends CommitInfo {
    files: string[];
}

export interface CommitListResponse {
    commits: CommitInfo[];
}

export interface CheckoutRequest {
    commit_sha: string;
    keep?: boolean;
}

export interface CheckoutResponse {
    ok: boolean;
    commit_sha: string;
    removed: number;
    user_content: string;
}
