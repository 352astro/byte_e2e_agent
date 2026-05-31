// ── 后端枚举常量（从 types.ts 透传，与 shared/types.py 一致）──
//
// MessageRole:  "user" | "assistant" | "tool"
// MessageStatus: "streaming" | "complete"
// StreamEventKind: "message_start" | "chunk_delta" | "chunk_complete"
//                   | "message_finish" | "turn_complete" | "interrupted"

export type { MessageRole, MessageStatus, StreamEventKind } from "./types";
