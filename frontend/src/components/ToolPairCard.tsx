import { ShellCard, WriteReadCard, DefaultToolCard } from "./ToolCards";
import type { ToolPair } from "../types";

// ── Public ───────────────────────────────────────────────

interface ToolPairCardProps {
    pair: ToolPair;
    defaultCollapsed?: boolean;
}

export default function ToolPairCard({
    pair,
    defaultCollapsed = false,
}: ToolPairCardProps) {
    const resultContent = pair.result
        ? String((pair.result.message as Record<string, unknown>).result || "")
        : undefined;

    switch (pair.toolName) {
        case "Shell":
            return (
                <ShellCard
                    cardId={`${pair.callTranscriptId}/${pair.callIndex}`}
                    args={pair.arguments}
                    defaultCollapsed={defaultCollapsed}
                    focusId={`${pair.callTranscriptId}/${pair.callIndex}`}
                    resultContent={resultContent}
                />
            );
        case "Write":
            return (
                <WriteReadCard
                    cardId={`${pair.callTranscriptId}/write`}
                    args={pair.arguments}
                    variant="Write"
                    defaultCollapsed={defaultCollapsed}
                    focusId={`${pair.callTranscriptId}/${pair.callIndex}`}
                    bodyContent={
                        pair.arguments
                            ? (() => {
                                  // parse content from args
                                  try {
                                      const obj = JSON.parse(pair.arguments);
                                      return obj.content != null
                                          ? String(obj.content)
                                          : undefined;
                                  } catch {
                                      return undefined;
                                  }
                              })()
                            : undefined
                    }
                />
            );
        case "Read":
            return (
                <WriteReadCard
                    cardId={`${pair.callTranscriptId}/read`}
                    args={pair.arguments}
                    variant="Read"
                    defaultCollapsed={defaultCollapsed}
                    focusId={`${pair.callTranscriptId}/${pair.callIndex}`}
                    bodyContent={resultContent}
                />
            );
        default:
            return (
                <DefaultToolCard
                    cardId={`${pair.callTranscriptId}/${pair.callIndex}`}
                    toolName={pair.toolName}
                    args={pair.arguments}
                    defaultCollapsed={defaultCollapsed}
                    focusId={`${pair.callTranscriptId}/${pair.callIndex}`}
                    resultContent={resultContent}
                />
            );
    }
}
