// ── Backend-kind constants (single source of truth) ──────

export const TranscriptKind = {
  UserQuestion: "user_question",
  Assistant: "assistant",
  ToolResult: "tool_result",
  Error: "error",
  PermissionRequest: "permission_request",
  PermissionResponse: "permission_response",
} as const;
export type TranscriptKind =
  (typeof TranscriptKind)[keyof typeof TranscriptKind];

export const ChunkKind = {
  Thinking: "thinking",
  Response: "response",
  ToolName: "tool_name",
  ToolArguments: "tool_arguments",
  ToolResult: "tool_result",
} as const;
export type ChunkKind = (typeof ChunkKind)[keyof typeof ChunkKind];
