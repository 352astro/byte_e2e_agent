import React, { useEffect, useMemo, useState } from "react";
import { renderToolCard } from "./ToolCards";
import CollapsibleCard from "./CollapsibleCard";
import Icon from "./Icon";
import MessageCard from "./MessageCard";
import { pairToolCalls } from "../hooks/pairTools";
import { useCollapsible } from "../hooks/useCollapsible";
import { extractArg, extractToolMeta } from "../utils";
import type { Message, StreamEvent, ToolPair } from "../types";

// ── Public ───────────────────────────────────────────────

interface ToolPairCardProps {
  pair: ToolPair;
  defaultCollapsed?: boolean;
  depth?: number;
}

function emptyMessage(id: string, turnId: string, role: string): Message {
  return {
    id,
    turn_id: turnId,
    role: role || "assistant",
    status: "streaming",
    content: "",
    reasoning: "",
    tool_calls: [],
    tool_result: "",
    tool_call_id: "",
    tool_name: "",
    error: "",
  } as Message;
}

function emptyTC(): Record<string, unknown> {
  return { id: "", type: "function", function: { name: "", arguments: "" } };
}

function reduceStreamEvent(
  messages: Message[],
  active: Message | null,
  ev: StreamEvent,
): { messages: Message[]; active: Message | null; done: boolean } {
  const updateMessage = (updater: (msg: Message) => Message) => {
    if (active?.id === ev.message_id) {
      return { messages, active: updater(active), done: false };
    }
    const existing = messages.find((msg) => msg.id === ev.message_id);
    if (existing?.status === "complete" && ev.kind === "chunk_delta") {
      return { messages, active, done: false };
    }
    let changed = false;
    const nextMessages = messages.map((msg) => {
      if (msg.id !== ev.message_id) return msg;
      changed = true;
      return updater(msg);
    });
    return {
      messages: changed ? nextMessages : messages,
      active,
      done: false,
    };
  };

  switch (ev.kind) {
    case "message_start": {
      if (
        messages.some((m) => m.id === ev.message_id) ||
        active?.id === ev.message_id
      ) {
        return { messages, active, done: false };
      }
      const nextMessages = active ? [...messages, active] : messages;
      return {
        messages: nextMessages,
        active: emptyMessage(ev.message_id, ev.turn_id, ev.role),
        done: false,
      };
    }
    case "chunk_delta": {
      if (ev.field === "tool_calls") {
        return updateMessage((msg) => {
          const idx = ev.tool_index >= 0 ? ev.tool_index : 0;
          const tcs = [...(msg.tool_calls || [])] as Record<string, any>[];
          while (tcs.length <= idx) tcs.push(emptyTC() as any);
          const srcFn = tcs[idx].function || { name: "", arguments: "" };
          const fn = {
            name: srcFn.name || "",
            arguments: srcFn.arguments || "",
          };
          if (ev.sub_field === "name") fn.name += ev.delta;
          if (ev.sub_field === "args") fn.arguments += ev.delta;
          tcs[idx] = { ...tcs[idx], function: fn };
          return { ...msg, tool_calls: tcs as any };
        });
      }
      return updateMessage((msg) => ({
        ...msg,
        [ev.field]: ((msg as any)[ev.field] || "") + ev.delta,
      }));
    }
    case "chunk_complete": {
      if (ev.field === "tool_calls" || ev.field === "tool_meta") {
        return { messages, active, done: false };
      }
      return updateMessage((msg) => ({ ...msg, [ev.field]: ev.full_content }));
    }
    case "message_finish": {
      if (!active || active.id !== ev.message_id) {
        return { messages, active, done: false };
      }
      return {
        messages: [...messages, { ...active, status: "complete" as const }],
        active: null,
        done: false,
      };
    }
    case "turn_complete":
    case "interrupted":
      return {
        messages: active
          ? [...messages, { ...active, status: "complete" as const }]
          : messages,
        active: null,
        done: true,
      };
  }
}

function parseArgs(raw: string): Record<string, unknown> {
  try {
    return JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function childSidFromResult(result: string | undefined): string {
  if (!result) return "";
  return result.match(/SubAgent session ([A-Za-z0-9_-]+) completed/)?.[1] || "";
}

function SubAgentTranscript({
  sessionId,
  depth,
}: {
  sessionId: string;
  depth: number;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [active, setActive] = useState<Message | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "done" | "error">(
    "loading",
  );

  useEffect(() => {
    const controller = new AbortController();
    let localMessages: Message[] = [];
    let localActive: Message | null = null;

    const publish = (done = false) => {
      setMessages(localMessages);
      setActive(localActive);
      setStatus(done ? "done" : "ready");
    };

    (async () => {
      try {
        const res = await fetch(`/api/session/${sessionId}/stream`, {
          signal: controller.signal,
        });
        if (!res.ok || !res.body)
          throw new Error(`Server returned ${res.status}`);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() || "";
          for (const part of parts) {
            const line = part.trim();
            if (!line.startsWith("data: ")) continue;
            const event = JSON.parse(line.slice(6)) as StreamEvent;
            const next = reduceStreamEvent(localMessages, localActive, event);
            localMessages = next.messages;
            localActive = next.active;
            publish(next.done);
          }
        }
        publish(true);
      } catch {
        if (!controller.signal.aborted) setStatus("error");
      }
    })();

    return () => controller.abort();
  }, [sessionId]);

  const visibleMessages = active ? [...messages, active] : messages;
  const transcriptMessages = useMemo(() => {
    let skippedInitialUser = false;
    return visibleMessages.filter((msg) => {
      if (!skippedInitialUser && msg.role === "user") {
        skippedInitialUser = true;
        return false;
      }
      return true;
    });
  }, [visibleMessages]);
  const pairs = useMemo(
    () => pairToolCalls(transcriptMessages, 0),
    [transcriptMessages],
  );
  const pairsByCallId = useMemo(() => {
    const map = new Map<string, ToolPair[]>();
    for (const p of pairs) {
      const bucket = map.get(p.callMessageId) || [];
      bucket.push(p);
      map.set(p.callMessageId, bucket);
    }
    return map;
  }, [pairs]);
  const pairedResultIds = useMemo(() => {
    const ids = new Set<string>();
    for (const p of pairs) {
      if (p.resultMessage) ids.add(p.resultMessage.id);
    }
    return ids;
  }, [pairs]);
  const pairedResultToolCallIds = useMemo(() => {
    const ids = new Set<string>();
    for (const p of pairs) {
      if (p.resultMessage && p.toolCall.id) ids.add(p.toolCall.id);
    }
    return ids;
  }, [pairs]);

  return (
    <div className="subagent-transcript">
      {status === "loading" && (
        <div className="subagent-status">Connecting to subagent...</div>
      )}
      {status === "error" && (
        <div className="subagent-status subagent-status--error">
          Unable to load subagent transcript.
        </div>
      )}
      {transcriptMessages.map((msg) => {
        if (pairedResultIds.has(msg.id)) return null;
        if (
          msg.role === "tool" &&
          msg.tool_call_id &&
          pairedResultToolCallIds.has(msg.tool_call_id)
        ) {
          return null;
        }
        const childPairs = pairsByCallId.get(msg.id);
        if (childPairs) {
          return (
            <div key={msg.id} className="subagent-message">
              <MessageCard message={msg} hideToolCards />
              {childPairs.map((childPair) => (
                <ToolPairCard
                  key={`${childPair.callMessageId}/${childPair.callIndex}`}
                  pair={childPair}
                  defaultCollapsed={depth > 0}
                  depth={depth + 1}
                />
              ))}
            </div>
          );
        }
        return (
          <div key={msg.id} className="subagent-message">
            <MessageCard message={msg} />
          </div>
        );
      })}
    </div>
  );
}

function SubAgentToolCard({
  pair,
  defaultCollapsed,
  depth,
}: {
  pair: ToolPair;
  defaultCollapsed: boolean;
  depth: number;
}) {
  const [collapsed, toggle] = useCollapsible(defaultCollapsed);
  const args = parseArgs(pair.toolCall?.function?.arguments || "");
  const meta = ((pair.toolCall as any)?.tool_meta || {}) as Record<
    string,
    unknown
  >;
  const resultContent = pair.resultMessage?.tool_result || "";
  const toolStatus = pair.resultMessage?.tool_status || "";
  const toolStatusSource = pair.resultMessage?.tool_status_source || "";
  const toolStatusReason = pair.resultMessage?.tool_status_reason || "";
  const childSessionId =
    String(meta.child_session_id || "") || childSidFromResult(resultContent);
  const status =
    toolStatus && toolStatus !== "success"
      ? toolStatus
      : String(meta.status || (resultContent ? "complete" : "running"));
  const prompt = String(args.prompt || "");
  const maxSteps = args.max_steps != null ? String(args.max_steps) : "";
  const canNest = Boolean(childSessionId) && depth < 3;

  return (
    <CollapsibleCard
      id={`${pair.callMessageId}/${pair.callIndex}/subagent`}
      collapsed={collapsed}
      onToggle={toggle}
      cardClassName="tool-card--subagent"
      headerClassName="subagent-card-header"
      title={
        <>
          <Icon name="robot" size={14} className="subagent-card-icon" />
          <span className="subagent-card-label">SubAgent</span>
          {childSessionId && (
            <span className="subagent-card-sid">{childSessionId}</span>
          )}
        </>
      }
      headerRight={
        <span
          className={`subagent-card-state subagent-card-state--${status}`}
          title={toolStatusReason || toolStatusSource}
        >
          {status}
        </span>
      }
    >
      <div className="subagent-card-body">
        {(prompt || maxSteps) && (
          <div className="subagent-meta">
            {maxSteps && <span>max {maxSteps}</span>}
            {prompt && <span title={prompt}>{prompt}</span>}
          </div>
        )}
        {canNest ? (
          <SubAgentTranscript sessionId={childSessionId} depth={depth + 1} />
        ) : resultContent ? (
          <pre className="subagent-result">{resultContent}</pre>
        ) : (
          <div className="subagent-status">Waiting for subagent session...</div>
        )}
      </div>
    </CollapsibleCard>
  );
}

const ToolPairCard = React.memo(function ToolPairCard({
  pair,
  defaultCollapsed = false,
  depth = 0,
}: ToolPairCardProps) {
  const toolName = pair.toolCall?.function?.name || "unknown";
  const argumentsStr = pair.toolCall?.function?.arguments || "";

  const resultContent = pair.resultMessage?.tool_result || undefined;
  const toolStatus = pair.resultMessage?.tool_status || undefined;
  const toolStatusSource = pair.resultMessage?.tool_status_source || undefined;
  const toolStatusReason = pair.resultMessage?.tool_status_reason || undefined;
  const { meta, rest } = extractToolMeta(argumentsStr, toolName);
  const cwd = meta.cwd as string | undefined;
  const filePath =
    (meta.path as string | undefined) || extractArg(argumentsStr, "path");
  const subtitle =
    toolName === "Shell" && cwd && cwd !== "." ? (
      <span className="shell-call-cwd">{cwd}</span>
    ) : (toolName === "Read" || toolName === "Write") && filePath ? (
      <span className="file-call-path">{filePath}</span>
    ) : undefined;

  const bodyContent = toolName === "Write" && rest ? rest : undefined;

  if (toolName === "SubAgent") {
    return (
      <SubAgentToolCard
        pair={pair}
        defaultCollapsed={defaultCollapsed}
        depth={depth}
      />
    );
  }

  return renderToolCard({
    id: `${pair.callMessageId}/${pair.callIndex}`,
    toolName,
    args: argumentsStr,
    active: resultContent === undefined,
    defaultCollapsed,
    resultContent,
    bodyContent,
    focusId: `${pair.callMessageId}/${pair.callIndex}`,
    subtitle,
    toolStatus,
    toolStatusSource,
    toolStatusReason,
  });
});

export default ToolPairCard;
