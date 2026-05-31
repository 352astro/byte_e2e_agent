/**
 * Pure reducer: apply a StreamEvent to a Message list.
 * No side effects, no React state — testable in isolation.
 *
 * NOTE: This module is no longer used by useAgentStream (now uses
 * activeMessage pattern). Kept for unit test coverage only.
 */
import type { Message, StreamEvent, ToolCall } from "../types";

function emptyTC(): ToolCall {
  return {
    id: "",
    type: "function",
    function: { name: "", arguments: "" },
  } as ToolCall;
}

function ensureSlots(tcs: ToolCall[], index: number): ToolCall[] {
  while (tcs.length <= index) tcs.push(emptyTC());
  return tcs;
}

export function reduceMessages(
  messages: Message[],
  event: StreamEvent,
): Message[] {
  switch (event.kind) {
    case "message_start": {
      if (messages.find((m) => m.id === event.message_id)) return messages;
      return [
        ...messages,
        {
          id: event.message_id,
          turn_id: event.turn_id,
          role: event.role || "assistant",
          status: "streaming",
          content: "",
          reasoning: "",
          tool_calls: [],
          tool_result: "",
          tool_call_id: "",
          tool_name: "",
          error: "",
        } as Message,
      ];
    }

    case "chunk_delta": {
      const { message_id: mid, field, delta, tool_index, sub_field } = event;
      return messages.map((m) => {
        if (m.id !== mid) return m;

        if (field === "tool_calls") {
          const idx = tool_index >= 0 ? tool_index : 0;
          const tcs = ensureSlots([...(m.tool_calls || [])], idx);
          const tc = { ...tcs[idx] };
          const fn = {
            name: tc.function?.name || "",
            arguments: tc.function?.arguments || "",
          };

          if (sub_field === "name") {
            fn.name += delta;
          } else if (sub_field === "args") {
            fn.arguments += delta;
          }
          tc.function = fn as ToolCall["function"];
          tcs[idx] = tc;

          return {
            ...m,
            tool_calls: tcs,
            _toolCallsRaw:
              (((m as Record<string, unknown>)._toolCallsRaw as string) || "") +
              delta,
          };
        }

        const current = (m as Record<string, unknown>)[field as string];
        return {
          ...m,
          [field]: (typeof current === "string" ? current : "") + delta,
        };
      });
    }

    case "chunk_complete": {
      const field = event.field as keyof Message;
      return messages.map((m) =>
        m.id === event.message_id ? { ...m, [field]: event.full_content } : m,
      );
    }

    case "message_finish": {
      return messages.map((m) => {
        if (m.id !== event.message_id) return m;
        const cleaned = { ...m, status: "complete" as const };
        if (Array.isArray(m.tool_calls) && m.tool_calls.length > 0) {
          delete (cleaned as Record<string, unknown>)._toolCallsRaw;
        }
        return cleaned;
      });
    }

    case "turn_complete":
    case "interrupted":
      return messages;

    default:
      return messages;
  }
}
