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
  const toolName = pair.toolCall?.function?.name || "unknown";
  const argumentsStr = pair.toolCall?.function?.arguments || "";

  const resultContent = pair.resultMessage?.tool_result || undefined;

  const bodyContent =
    toolName === "Write" && argumentsStr
      ? (() => {
          try {
            const obj = JSON.parse(argumentsStr);
            return obj.content != null ? String(obj.content) : undefined;
          } catch {
            return undefined;
          }
        })()
      : undefined;

  return renderToolCard({
    id: `${pair.callMessageId}/${pair.callIndex}`,
    toolName,
    args: argumentsStr,
    defaultCollapsed,
    resultContent,
    bodyContent,
    focusId: `${pair.callMessageId}/${pair.callIndex}`,
  });
});

export default ToolPairCard;
