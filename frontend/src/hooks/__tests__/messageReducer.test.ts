import { describe, it, expect } from "vitest";
import { reduceMessages } from "../messageReducer";
import type { Message, StreamEvent } from "../../types";

function ev(overrides: Partial<StreamEvent> = {}): StreamEvent {
  return {
    kind: "chunk_delta",
    session_id: "",
    message_id: "m1",
    turn_id: "turn-1",
    role: "",
    field: "content",
    delta: "",
    tool_index: -1,
    sub_field: "",
    full_content: "",
    tool_name: "",
    tool_args: "",
    is_error: false,
    input_tokens: 0,
    output_tokens: 0,
    reason: "",
    ...overrides,
  };
}

// ═══════════════════════════════════════════════════════════
// message_start — role propagation
// ═══════════════════════════════════════════════════════════

describe("message_start", () => {
  it("uses ev.role when provided", () => {
    const result = reduceMessages(
      [],
      ev({
        kind: "message_start",
        message_id: "u1",
        turn_id: "t1",
        role: "user",
      }),
    );
    expect(result[0].role).toBe("user");
  });

  it("defaults to assistant when role is empty", () => {
    const result = reduceMessages(
      [],
      ev({ kind: "message_start", message_id: "a1", turn_id: "t1", role: "" }),
    );
    expect(result[0].role).toBe("assistant");
  });

  it("does not duplicate existing message_id", () => {
    const msgs: Message[] = [
      {
        id: "a1",
        role: "assistant",
        status: "streaming",
        content: "x",
      } as Message,
    ];
    const result = reduceMessages(
      msgs,
      ev({ kind: "message_start", message_id: "a1" }),
    );
    expect(result).toHaveLength(1);
  });
});

// ═══════════════════════════════════════════════════════════
// chunk_delta — content / reasoning (unchanged)
// ═══════════════════════════════════════════════════════════

describe("chunk_delta — text fields", () => {
  it("appends content", () => {
    const init = reduceMessages(
      [],
      ev({ kind: "message_start", message_id: "a1", turn_id: "t1" }),
    );
    const r1 = reduceMessages(
      init,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "content",
        delta: "Hello",
      }),
    );
    const r2 = reduceMessages(
      r1,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "content",
        delta: " World",
      }),
    );
    expect(r2[0].content).toBe("Hello World");
  });

  it("appends reasoning", () => {
    const init = reduceMessages(
      [],
      ev({ kind: "message_start", message_id: "a1", turn_id: "t1" }),
    );
    const r1 = reduceMessages(
      init,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "reasoning",
        delta: "Need",
      }),
    );
    const r2 = reduceMessages(
      r1,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "reasoning",
        delta: " to think",
      }),
    );
    expect(r2[0].reasoning).toBe("Need to think");
  });
});

// ═══════════════════════════════════════════════════════════
// chunk_delta — tool_calls (NEW: sub_field + tool_index)
// ═══════════════════════════════════════════════════════════

describe("chunk_delta — tool_calls streaming", () => {
  it("builds tool name incrementally via sub_field=name", () => {
    const init = reduceMessages(
      [],
      ev({ kind: "message_start", message_id: "a1", turn_id: "t1" }),
    );
    const r1 = reduceMessages(
      init,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "name",
        delta: "S",
        tool_index: 0,
      }),
    );
    const r2 = reduceMessages(
      r1,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "name",
        delta: "h",
        tool_index: 0,
      }),
    );
    const r3 = reduceMessages(
      r2,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "name",
        delta: "e",
        tool_index: 0,
      }),
    );
    const r4 = reduceMessages(
      r3,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "name",
        delta: "l",
        tool_index: 0,
      }),
    );
    const r5 = reduceMessages(
      r4,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "name",
        delta: "l",
        tool_index: 0,
      }),
    );
    expect(r5[0].tool_calls[0]!.function!.name as string).toBe("Shell");
  });

  it("builds tool args incrementally via sub_field=args", () => {
    const init = reduceMessages(
      [],
      ev({ kind: "message_start", message_id: "a1", turn_id: "t1" }),
    );
    // First set name
    const r1 = reduceMessages(
      init,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "name",
        delta: "Shell",
        tool_index: 0,
      }),
    );
    // Then args
    const r2 = reduceMessages(
      r1,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "args",
        delta: "{",
        tool_index: 0,
      }),
    );
    const r3 = reduceMessages(
      r2,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "args",
        delta: '"cmd"',
        tool_index: 0,
      }),
    );
    const r4 = reduceMessages(
      r3,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "args",
        delta: ":",
        tool_index: 0,
      }),
    );
    const r5 = reduceMessages(
      r4,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "args",
        delta: '"ls"',
        tool_index: 0,
      }),
    );
    const r6 = reduceMessages(
      r5,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "args",
        delta: "}",
        tool_index: 0,
      }),
    );
    expect(r6[0].tool_calls[0]!.function!.name as string).toBe("Shell");
    expect(r6[0].tool_calls[0]!.function!.arguments as string).toBe('{"cmd":"ls"}');
  });

  it("streams multiple tools with different tool_index", () => {
    const init = reduceMessages(
      [],
      ev({ kind: "message_start", message_id: "a1", turn_id: "t1" }),
    );
    // Tool 0: Shell
    let msgs = reduceMessages(
      init,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "name",
        delta: "Shell",
        tool_index: 0,
      }),
    );
    msgs = reduceMessages(
      msgs,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "args",
        delta: '{"cmd":"ls"}',
        tool_index: 0,
      }),
    );
    // Tool 1: Read
    msgs = reduceMessages(
      msgs,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "name",
        delta: "Read",
        tool_index: 1,
      }),
    );
    msgs = reduceMessages(
      msgs,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "args",
        delta: '{"path":"f.py"}',
        tool_index: 1,
      }),
    );

    expect(msgs[0].tool_calls).toHaveLength(2);
    expect(msgs[0].tool_calls[0]!.function!.name as string).toBe("Shell");
    expect(msgs[0].tool_calls[0]!.function!.arguments as string).toBe('{"cmd":"ls"}');
    expect(msgs[0].tool_calls[1]!.function!.name as string).toBe("Read");
    expect(msgs[0].tool_calls[1]!.function!.arguments as string).toBe('{"path":"f.py"}');
  });

  it("accumulates _toolCallsRaw for streaming display", () => {
    const init = reduceMessages(
      [],
      ev({ kind: "message_start", message_id: "a1", turn_id: "t1" }),
    );
    const r1 = reduceMessages(
      init,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "name",
        delta: "Shell",
        tool_index: 0,
      }),
    );
    const r2 = reduceMessages(
      r1,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "args",
        delta: "{}",
        tool_index: 0,
      }),
    );
    expect((r2[0] as Record<string, unknown>)._toolCallsRaw).toBe("Shell{}");
  });
});

// ═══════════════════════════════════════════════════════════
// Full assembly — combination of all field types
// ═══════════════════════════════════════════════════════════

describe("full message assembly", () => {
  it("content-only: start → delta×3 → finish", () => {
    let msgs: Message[] = [];
    msgs = reduceMessages(
      msgs,
      ev({
        kind: "message_start",
        message_id: "a1",
        turn_id: "t1",
        role: "assistant",
      }),
    );
    msgs = reduceMessages(
      msgs,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "content",
        delta: "I think so.",
      }),
    );
    msgs = reduceMessages(
      msgs,
      ev({ kind: "message_finish", message_id: "a1" }),
    );
    expect(msgs[0].content).toBe("I think so.");
    expect(msgs[0].status).toBe("complete");
  });

  it("user + assistant + tool messages in sequence", () => {
    let msgs: Message[] = [];

    // User
    msgs = reduceMessages(
      msgs,
      ev({
        kind: "message_start",
        message_id: "u1",
        turn_id: "t1",
        role: "user",
      }),
    );
    // (user messages are complete immediately — simulated by finish)
    msgs = reduceMessages(
      msgs,
      ev({ kind: "message_finish", message_id: "u1" }),
    );

    // Assistant with tool call
    msgs = reduceMessages(
      msgs,
      ev({
        kind: "message_start",
        message_id: "a1",
        turn_id: "t1",
        role: "assistant",
      }),
    );
    msgs = reduceMessages(
      msgs,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "reasoning",
        delta: "Need to run command",
      }),
    );
    msgs = reduceMessages(
      msgs,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "name",
        delta: "Shell",
        tool_index: 0,
      }),
    );
    msgs = reduceMessages(
      msgs,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "tool_calls",
        sub_field: "args",
        delta: '{"cmd":"ls"}',
        tool_index: 0,
      }),
    );
    msgs = reduceMessages(
      msgs,
      ev({ kind: "message_finish", message_id: "a1" }),
    );

    // Tool result
    msgs = reduceMessages(
      msgs,
      ev({
        kind: "message_start",
        message_id: "r1",
        turn_id: "t1",
        role: "tool",
      }),
    );
    msgs = reduceMessages(
      msgs,
      ev({ kind: "message_finish", message_id: "r1" }),
    );

    expect(msgs).toHaveLength(3);
    expect(msgs[0].role).toBe("user");
    expect(msgs[1].role).toBe("assistant");
    expect(msgs[1].tool_calls[0]!.function!.name as string).toBe("Shell");
    expect(msgs[2].role).toBe("tool");
  });

  it("is a pure function — does not mutate input", () => {
    const input: Message[] = [
      { id: "m1", role: "user", status: "complete", content: "q" } as Message,
    ];
    const snapshot = JSON.stringify(input);
    reduceMessages(
      input,
      ev({ kind: "message_start", message_id: "a1", turn_id: "t1" }),
    );
    reduceMessages(
      input,
      ev({
        kind: "chunk_delta",
        message_id: "a1",
        field: "content",
        delta: "x",
      }),
    );
    expect(JSON.stringify(input)).toBe(snapshot);
  });
});
