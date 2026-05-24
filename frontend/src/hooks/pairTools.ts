import type { DisplayTranscript, ToolPair } from "../types";

/**
 * Pair tool calls (inside assistant transcripts) with their tool_result transcripts.
 *
 * During streaming: `startFrom` limits scanning to recent transcripts.
 * During recover: `startFrom` = 0 scans everything.
 */
export function pairToolCalls(
  transcripts: DisplayTranscript[],
  startFrom = 0,
): ToolPair[] {
  // Collect all existing pairs first (from previous pairing)
  const pairs: ToolPair[] = [];

  // Scan for tool calls in assistant transcripts
  for (let i = startFrom; i < transcripts.length; i++) {
    const t = transcripts[i];
    if (t.kind !== "assistant") continue;

    const toolCalls = (t.message as Record<string, unknown>)
      .tool_calls as Array<Record<string, unknown>> | undefined;
    if (!toolCalls || !Array.isArray(toolCalls)) continue;

    for (let ci = 0; ci < toolCalls.length; ci++) {
      const tc = toolCalls[ci];
      const fn = (tc.function || {}) as Record<string, unknown>;
      const toolCallId = String(tc.id || "");
      const toolName = String(fn.name || "");
      const args = String(fn.arguments || "");

      // Find matching tool_result transcript (search forward)
      let result: DisplayTranscript | undefined;
      for (let j = i + 1; j < transcripts.length; j++) {
        const rt = transcripts[j];
        if (rt.kind !== "tool_result") continue;
        const rtCallId = (rt.message as Record<string, unknown>).tool_call_id;
        if (String(rtCallId) === toolCallId) {
          result = rt;
          break;
        }
      }

      pairs.push({
        callTranscriptId: t.id,
        callIndex: ci,
        toolCallId,
        toolName,
        arguments: args,
        result,
      });
    }
  }

  return pairs;
}
