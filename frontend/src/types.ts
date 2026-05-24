// ── Transcript ──────────────────────────────────────────

export interface Transcript {
    id: string;
    kind: string;
    message: Record<string, unknown>;
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
      };

// ── Display items ────────────────────────────────────────

export interface DisplayTranscript {
    id: string;
    kind: string;
    message: Record<string, unknown>;
    subStreams: SubStream[]; // completed sub-streams, in order
    activeSubStream: SubStream | null; // currently streaming
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
