/**
 * Pure reducer: apply a StreamEvent to a Message list.
 * No side effects, no React state — testable in isolation.
 *
 * Mirrors backend Hook build logic exactly (actions.py model_call):
 *   content              → chunk_delta: msg.content += delta
 *   reasoning            → chunk_delta: msg.reasoning += delta
 *   tool_calls[n].name   → chunk_delta: field="tool_calls", sub_field="name",  tool_index=n
 *   tool_calls[n].args   → chunk_delta: field="tool_calls", sub_field="args",  tool_index=n
 *   tool_result / error  → chunk_complete 一次性赋值
 *   status               → message_start: "streaming"; message_finish: "complete"
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
    // ── message_start — 创建占位 Message ─────────────
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

    // ── chunk_delta — msg[field] += delta ─────────────
    case "chunk_delta": {
      const { message_id: mid, field, delta, tool_index, sub_field } = event;
      return messages.map((m) => {
        if (m.id !== mid) return m;

        // Tool calls: mirror backend if tc_name / if tc_args
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
            // Keep raw buffer for streaming text display
            _toolCallsRaw:
              (((m as Record<string, unknown>)._toolCallsRaw as string) || "") +
              delta,
          };
        }

        // Text fields: simple append
        const current = (m as Record<string, unknown>)[field as string];
        return {
          ...m,
          [field]: (typeof current === "string" ? current : "") + delta,
        };
      });
    }

    // ── chunk_complete — 结构化字段一次性赋值 ────────
    case "chunk_complete": {
      const field = event.field as keyof Message;
      return messages.map((m) =>
        m.id === event.message_id ? { ...m, [field]: event.full_content } : m,
      );
    }

    // ── message_finish — 标记完成 + 清理 ─────────────
    case "message_finish": {
      return messages.map((m) => {
        if (m.id !== event.message_id) return m;
        const cleaned = { ...m, status: "complete" as const };
        // Keep _toolCallsRaw as fallback if tool_calls never populated
        if (Array.isArray(m.tool_calls) && m.tool_calls.length > 0) {
          delete (cleaned as Record<string, unknown>)._toolCallsRaw;
        }
        return cleaned;
      });
    }

    // ── turn_complete / interrupted — 不修改消息 ──────
    case "turn_complete":
    case "interrupted":
      return messages;

    default:
      return messages;
  }
}
