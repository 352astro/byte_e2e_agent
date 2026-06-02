import type { Message, ToolPair, ToolCall } from "../types";

/**
 * Pair tool calls inside assistant messages with their tool_result messages.
 *
 * During streaming: `startFrom` limits scanning to recent messages.
 * During recover: `startFrom` = 0 scans everything.
 */
export function pairToolCalls(messages: Message[], startFrom = 0): ToolPair[] {
  const pairs: ToolPair[] = [];
  const usedResultIds = new Set<string>();

  for (let i = startFrom; i < messages.length; i++) {
    const m = messages[i];
    if (m.role !== "assistant") continue;

    const toolCalls: ToolCall[] = m.tool_calls || [];
    if (!toolCalls.length) continue;

    for (let ci = 0; ci < toolCalls.length; ci++) {
      const tc = toolCalls[ci];
      const toolCallId = tc.id || "";

      // Find matching tool_result message (search forward)
      let resultMessage: Message | undefined;
      for (let j = i + 1; j < messages.length; j++) {
        const rm = messages[j];
        if (rm.role !== "tool") continue;
        if (usedResultIds.has(rm.id)) continue;
        if (toolCallId && rm.tool_call_id === toolCallId) {
          resultMessage = rm;
          break;
        }
      }
      if (!resultMessage) {
        const toolName = tc.function?.name || "";
        for (let j = i + 1; j < messages.length; j++) {
          const rm = messages[j];
          if (rm.role !== "tool") continue;
          if (usedResultIds.has(rm.id)) continue;
          if (rm.tool_call_id) continue;
          if (toolName && rm.tool_name && rm.tool_name !== toolName) continue;
          resultMessage = rm;
          break;
        }
      }
      if (resultMessage) {
        usedResultIds.add(resultMessage.id);
      }

      pairs.push({
        callMessageId: m.id,
        callIndex: ci,
        toolCall: tc,
        resultMessage,
      });
    }
  }

  return pairs;
}
