import React from "react";
import { useState, useCallback } from "react";
import Markdown from "./Markdown";
import Icon from "./Icon";
import CollapsibleCard from "./CollapsibleCard";
import ToolResult from "./ToolResult";
import TokenBubble from "./TokenBubble";
import { renderToolCard } from "./ToolCards";
import { useFocusedId } from "../hooks/FocusContext";
import { extractArg, extractToolMeta } from "../utils";
import type { Message, ToolCall } from "../types";

// ── Public component ─────────────────────────────────────

interface MessageCardProps {
  message: Message;
  hideToolCards?: boolean;
}

const MessageCard = React.memo(function MessageCard({
  message: m,
  hideToolCards = false,
}: MessageCardProps) {
  const focusedId = useFocusedId();
  const [expandedThinking, setExpandedThinking] = useState<Set<string>>(
    new Set(),
  );
  const [collapsedCards, setCollapsedCards] = useState<Set<string>>(new Set());

  const toggleThinking = useCallback((id: string) => {
    setExpandedThinking((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  const toggleCard = useCallback((id: string) => {
    setCollapsedCards((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  const isStreaming = m.status === "streaming";

  // ── User ────────────────────────────────────────
  if (m.role === "user") {
    return (
      <div className="user-bubble">
        <span className="user-bubble-label">You</span>
        <p>{m.content}</p>
      </div>
    );
  }

  // ── Tool ────────────────────────────────────────
  if (m.role === "tool") {
    const toolName = m.tool_name || "Tool";
    const result = m.tool_result || "";
    let toolArgs: Record<string, unknown> | undefined;
    try {
      if (result) {
        // tool_result is the execution output; try parsing if it looks like JSON
      }
    } catch {
      /* ignore */
    }
    return (
      <ToolResult toolName={toolName} result={result} toolArgs={toolArgs} />
    );
  }

  // ── Error ────────────────────────────────────────
  if (m.error) {
    return (
      <div className="transcript-card error-card">
        <span className="transcript-label">
          <Icon name="error" size={12} /> Error
        </span>
        <div className="transcript-body">{m.error}</div>
      </div>
    );
  }

  // ── Assistant ────────────────────────────────────

  const toolCalls: ToolCall[] = m.tool_calls || [];
  const hasThinking = (m.reasoning || "").length > 0;
  const hasContent = (m.content || "").length > 0;
  const showThinkingBlock = hasThinking || (isStreaming && !hasContent);

  return (
    <div className="message-row">
      <div className="transcript-card assistant-card">
        {/* Reasoning block */}
        {showThinkingBlock && (
          <CollapsibleCard
            id={`${m.id}/thinking`}
            dataFid={focusedId ? `${m.id}/thinking` : undefined}
            collapsed={
              !isStreaming && !expandedThinking.has(`${m.id}/thinking`)
            }
            onToggle={toggleThinking}
            headerClickable={!isStreaming}
            cardClassName={`thinking-block${expandedThinking.has(`${m.id}/thinking`) ? " thinking-block--open" : ""}${!isStreaming ? " thinking-block--done" : ""}`}
            headerClassName="thinking-header"
            title={
              <>
                <Icon name="bulb" size={14} className="thinking-bulb" />
                <span className="thinking-label">thinking</span>
              </>
            }
          >
            {hasThinking && (
              <div className="thinking-body">
                <Markdown text={m.reasoning} />
              </div>
            )}
            {!hasThinking && isStreaming && (
              <div className="thinking-body">
                <span className="message-empty-spinner" aria-label="Thinking" />
              </div>
            )}
          </CollapsibleCard>
        )}

        {/* Content block */}
        {hasContent && (
          <div
            className={`transcript-body no-focus-glow${focusedId === `${m.id}/content` ? " card-latest" : ""}`}
            data-fid={`${m.id}/content`}
          >
            <Markdown text={m.content} />
          </div>
        )}

        {/* Streaming indicator */}
        {isStreaming && !showThinkingBlock && !hasContent && (
          <div className="transcript-body streaming-indicator">
            <span className="message-empty-spinner" aria-label="Thinking" />
          </div>
        )}

        {/* Tool calls */}
        {!hideToolCards &&
          toolCalls.length > 0 &&
          toolCalls.map((tc, i) => {
            const tcId = `${m.id}/tc/${i}`;
            const fn = tc.function || { name: "", arguments: "" };
            const toolName =
              fn.name ||
              ((tc as Record<string, unknown>).tool_name as string) ||
              "unknown";
            const args = fn.arguments || "";
            const { meta } = extractToolMeta(args, toolName);
            const cwd = meta.cwd as string | undefined;
            const filePath =
              (meta.path as string | undefined) || extractArg(args, "path");
            const subtitle =
              toolName === "Shell" && cwd && cwd !== "." ? (
                <span className="shell-call-cwd">{cwd}</span>
              ) : (toolName === "Read" || toolName === "Write") && filePath ? (
                <span className="file-call-path">{filePath}</span>
              ) : undefined;
            const collapsed = collapsedCards.has(tcId);
            return (
              <span key={tcId}>
                {renderToolCard({
                  id: tcId,
                  toolName,
                  args,
                  active: isStreaming && i === toolCalls.length - 1,
                  collapsed,
                  onToggle: toggleCard,
                  subtitle,
                })}
              </span>
            );
          })}
        {/* Fallback: show raw tool call stream if structured is empty */}
        {!hideToolCards &&
          toolCalls.length === 0 &&
          (m as Record<string, unknown>)._toolCallsRaw && (
            <div className="tool-card">
              <div className="tool-card-header">
                <Icon name="tool" size={13} className="tool-icon" />
                <span className="tool-label">
                  {(m as Record<string, unknown>)._toolCallsRaw as string}
                </span>
              </div>
            </div>
          )}
        {/* Token usage bubble */}
        <TokenBubble
          usage={
            (m as Record<string, unknown>)._usage as
              | Record<string, unknown>
              | undefined
          }
          messageId={m.id}
        />
      </div>
    </div>
  );
});

export default MessageCard;
