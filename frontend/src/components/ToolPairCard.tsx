import React from "react";
import { renderToolCard } from "./ToolCards";
import type { ToolPair } from "../types";

// ── Public ───────────────────────────────────────────────

interface ToolPairCardProps {
    pair: ToolPair;
    defaultCollapsed?: boolean;
}

const ToolPairCard = React.memo(function ToolPairCard({
    pair,
    defaultCollapsed = false,
}: ToolPairCardProps) {
    const resultContent = pair.result
        ? String((pair.result.message as Record<string, unknown>).result || "")
        : undefined;

    const bodyContent =
        pair.toolName === "Write" && pair.arguments
            ? (() => {
                  try {
                      const obj = JSON.parse(pair.arguments);
                      return obj.content != null
                          ? String(obj.content)
                          : undefined;
                  } catch {
                      return undefined;
                  }
              })()
            : undefined;

    return renderToolCard({
        id: `${pair.callTranscriptId}/${pair.callIndex}`,
        toolName: pair.toolName,
        args: pair.arguments,
        defaultCollapsed,
        resultContent,
        bodyContent,
        focusId: `${pair.callTranscriptId}/${pair.callIndex}`,
    });
});

export default ToolPairCard;

