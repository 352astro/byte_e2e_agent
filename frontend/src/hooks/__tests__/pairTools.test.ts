import { describe, it, expect } from "vitest";
import { pairToolCalls } from "../pairTools";
import type { Message, ToolCall } from "../../types";

function makeMsg(overrides: Partial<Message> = {}): Message {
  return {
    id: "m1",
    turn_id: "t1",
    role: "assistant",
    status: "complete",
    content: "",
    reasoning: "",
    tool_calls: [],
    tool_result: "",
    tool_call_id: "",
    tool_name: "",
    error: "",
    ...overrides,
  } as Message;
}

function makeToolCall(id: string, name: string, args = "{}"): ToolCall {
  return {
    id,
    type: "function",
    function: { name, arguments: args },
  } as ToolCall;
}

describe("pairToolCalls", () => {
  it("returns empty for empty messages", () => {
    expect(pairToolCalls([])).toEqual([]);
  });

  it("skips assistant without tool_calls", () => {
    const msgs = [makeMsg({ role: "assistant", content: "hello" })];
    expect(pairToolCalls(msgs)).toEqual([]);
  });

  it("pairs assistant tool_call with matching tool_result", () => {
    const msgs: Message[] = [
      makeMsg({
        id: "a1",
        role: "assistant",
        tool_calls: [makeToolCall("tc1", "Shell", '{"cmd":"ls"}')],
      }),
      makeMsg({
        id: "r1",
        role: "tool",
        tool_call_id: "tc1",
        tool_name: "Shell",
        tool_result: "ok",
      }),
    ];

    const pairs = pairToolCalls(msgs);
    expect(pairs).toHaveLength(1);
    expect(pairs[0].callMessageId).toBe("a1");
    expect(pairs[0].callIndex).toBe(0);
    expect(pairs[0].toolCall.id).toBe("tc1");
    expect(pairs[0].resultMessage?.id).toBe("r1");
  });

  it("does not pair when tool_result is missing", () => {
    const msgs: Message[] = [
      makeMsg({
        id: "a1",
        role: "assistant",
        tool_calls: [makeToolCall("tc1", "Shell")],
      }),
      // no tool_result for tc1
    ];

    const pairs = pairToolCalls(msgs);
    expect(pairs).toHaveLength(1);
    expect(pairs[0].resultMessage).toBeUndefined();
  });

  it("does not pair with wrong tool_call_id", () => {
    const msgs: Message[] = [
      makeMsg({
        id: "a1",
        role: "assistant",
        tool_calls: [makeToolCall("tc1", "Shell")],
      }),
      makeMsg({
        id: "r1",
        role: "tool",
        tool_call_id: "tc2", // different!
        tool_result: "ok",
      }),
    ];

    const pairs = pairToolCalls(msgs);
    expect(pairs).toHaveLength(1);
    expect(pairs[0].resultMessage).toBeUndefined();
  });

  it("pairs multiple tool_calls with their results", () => {
    const msgs: Message[] = [
      makeMsg({
        id: "a1",
        role: "assistant",
        tool_calls: [makeToolCall("tc1", "Shell"), makeToolCall("tc2", "Read")],
      }),
      makeMsg({
        id: "r1",
        role: "tool",
        tool_call_id: "tc1",
        tool_name: "Shell",
        tool_result: "shell ok",
      }),
      makeMsg({
        id: "r2",
        role: "tool",
        tool_call_id: "tc2",
        tool_name: "Read",
        tool_result: "read ok",
      }),
    ];

    const pairs = pairToolCalls(msgs);
    expect(pairs).toHaveLength(2);
    expect(pairs[0].toolCall.id).toBe("tc1");
    expect(pairs[0].resultMessage?.id).toBe("r1");
    expect(pairs[1].toolCall.id).toBe("tc2");
    expect(pairs[1].resultMessage?.id).toBe("r2");
  });

  it("skips user and error messages", () => {
    const msgs: Message[] = [
      makeMsg({ id: "u1", role: "user", content: "hello" }),
      makeMsg({ id: "e1", role: "assistant", error: "boom" }),
      makeMsg({
        id: "a1",
        role: "assistant",
        tool_calls: [makeToolCall("tc1", "Shell")],
      }),
    ];

    // only a1 is a real assistant with tool_calls
    const pairs = pairToolCalls(msgs);
    expect(pairs).toHaveLength(1);
    expect(pairs[0].callMessageId).toBe("a1");
  });

  it("respects startFrom parameter", () => {
    const msgs: Message[] = [
      makeMsg({
        id: "a1",
        role: "assistant",
        tool_calls: [makeToolCall("tc1", "Shell")],
      }),
      makeMsg({
        id: "a2",
        role: "assistant",
        tool_calls: [makeToolCall("tc2", "Read")],
      }),
    ];

    // startFrom=1 skips a1
    const pairs = pairToolCalls(msgs, 1);
    expect(pairs).toHaveLength(1);
    expect(pairs[0].callMessageId).toBe("a2");
  });

  it("tool without function defaults gracefully", () => {
    const msgs: Message[] = [
      makeMsg({
        id: "a1",
        role: "assistant",
        tool_calls: [{ id: "tc1", type: "function" } as ToolCall],
      }),
      makeMsg({
        id: "r1",
        role: "tool",
        tool_call_id: "tc1",
        tool_result: "ok",
      }),
    ];

    const pairs = pairToolCalls(msgs);
    expect(pairs).toHaveLength(1);
    expect(pairs[0].toolCall.function?.name).toBeUndefined();
  });
});
