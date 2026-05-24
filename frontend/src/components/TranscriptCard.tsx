import { useState, useCallback } from "react";
import Markdown from "./Markdown";
import Icon from "./Icon";
import { TranscriptKind, ChunkKind } from "../constants";
import type { DisplayTranscript, SubStream } from "../types";

// ── helpers ──────────────────────────────────────────────

function groupToolCards(
  items: { ss: SubStream; active: boolean }[],
): Map<string, { name: string; args: string; active: boolean }> {
  const groups = new Map<
    string,
    { name: string; args: string; active: boolean }
  >();
  for (const { ss, active } of items) {
    if (ss.kind === ChunkKind.ToolName) {
      const g = groups.get(ss.id) || { name: "", args: "", active: false };
      g.name = ss.text;
      g.active = g.active || active;
      groups.set(ss.id, g);
    } else if (ss.kind === ChunkKind.ToolArguments) {
      const g = groups.get(ss.id) || { name: "", args: "", active: false };
      g.args = g.args ? g.args + ss.text : ss.text;
      g.active = g.active || active;
      groups.set(ss.id, g);
    }
  }
  return groups;
}

/** 从 message dict 重建 sub_streams（刷新恢复用）。 */
function rebuildFromMessage(
  tid: string,
  msg: Record<string, unknown>,
): SubStream[] {
  const result: SubStream[] = [];
  const reasoning = msg.reasoning_content;
  if (reasoning && typeof reasoning === "string") {
    result.push({ id: tid, kind: ChunkKind.Thinking, text: reasoning });
  }
  const content = msg.content;
  if (content && typeof content === "string") {
    result.push({ id: tid, kind: ChunkKind.Response, text: content });
  }
  const toolCalls = msg.tool_calls as
    | Array<Record<string, unknown>>
    | undefined;
  if (toolCalls && Array.isArray(toolCalls)) {
    for (let i = 0; i < toolCalls.length; i++) {
      const fn = (toolCalls[i].function || {}) as Record<string, unknown>;
      const tcId = `${tid}/tc/${i}`;
      if (fn.name) {
        result.push({
          id: tcId,
          kind: ChunkKind.ToolName,
          text: String(fn.name),
        });
      }
      if (fn.arguments) {
        result.push({
          id: tcId,
          kind: ChunkKind.ToolArguments,
          text: String(fn.arguments),
        });
      }
    }
  }
  return result;
}

// ── Sub-renderers ────────────────────────────────────────

function ThinkingBlock({
  ss,
  active,
  thinkingState,
  onToggle,
}: {
  ss: SubStream;
  active: boolean;
  thinkingState: Set<string>;
  onToggle: (id: string) => void;
}) {
  const done = !active;
  const expanded = active || thinkingState.has(ss.id);
  return (
    <div
      className={`thinking-block${expanded ? " thinking-block--open" : ""}${done ? " thinking-block--done" : ""}`}
    >
      <div className="thinking-header" onClick={() => done && onToggle(ss.id)}>
        <Icon name="bulb" size={14} className="thinking-bulb" />
        <span className="thinking-label">thinking</span>
        {done && (
          <Icon
            name={expanded ? "chevron-up" : "chevron-down"}
            size={10}
            className="thinking-chevron"
          />
        )}
      </div>
      {expanded && (
        <div className="thinking-body">
          <Markdown text={ss.text} />
        </div>
      )}
    </div>
  );
}

function ResponseBlock({ ss }: { ss: SubStream }) {
  return (
    <div className="transcript-body">
      <Markdown text={ss.text} />
    </div>
  );
}

function ToolResultBlock({ ss, active }: { ss: SubStream; active: boolean }) {
  return (
    <div className={`tool-card${active ? " tool-card--streaming" : ""}`}>
      <div className="tool-card-header">
        <Icon name="tool" size={13} className="tool-icon" />
        <span className="tool-label">Result</span>
      </div>
      <div className="tool-card-body">
        <div className="tool-code-block">
          <pre>
            <code>
              {ss.text.length > 500 ? ss.text.slice(0, 500) + "..." : ss.text}
            </code>
          </pre>
        </div>
      </div>
    </div>
  );
}

function ToolCard({
  name,
  args,
  active,
}: {
  name: string;
  args: string;
  active: boolean;
}) {
  return (
    <div className={`tool-card${active ? " tool-card--streaming" : ""}`}>
      <div className="tool-card-header">
        <Icon name="tool" size={13} className="tool-icon" />
        <span className="tool-label">{name || "\u2026"}</span>
      </div>
      <div className="tool-card-body">
        <div className="tool-code-block">
          <pre>
            <code>{args || "\u2026"}</code>
          </pre>
        </div>
      </div>
    </div>
  );
}

// ── Chunk renderer registry ──────────────────────────────

type ChunkRenderer = (props: {
  ss: SubStream;
  active: boolean;
  thinkingState: Set<string>;
  onToggleThinking: (id: string) => void;
}) => React.ReactNode;

const chunkRenderers: Partial<Record<string, ChunkRenderer>> = {
  [ChunkKind.Thinking]: ({ ss, active, thinkingState, onToggleThinking }) => (
    <ThinkingBlock
      ss={ss}
      active={active}
      thinkingState={thinkingState}
      onToggle={onToggleThinking}
    />
  ),
  [ChunkKind.Response]: ({ ss }) => <ResponseBlock ss={ss} />,
  [ChunkKind.ToolResult]: ({ ss, active }) => (
    <ToolResultBlock ss={ss} active={active} />
  ),
};

// ── Public component ─────────────────────────────────────

interface TranscriptCardProps {
  transcript: DisplayTranscript;
}

export default function TranscriptCard({ transcript: t }: TranscriptCardProps) {
  const [expandedThinking, setExpandedThinking] = useState<Set<string>>(
    new Set(),
  );

  const toggleThinking = useCallback((id: string) => {
    setExpandedThinking((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  // ── User question ────────────────────────────
  if (t.kind === TranscriptKind.UserQuestion) {
    const content = String(
      (t.message as Record<string, unknown>).content || "",
    );
    return (
      <div className="user-bubble">
        <span className="user-bubble-label">You</span>
        <p>{content}</p>
      </div>
    );
  }

  // ── Tool result ──────────────────────────────
  if (t.kind === TranscriptKind.ToolResult) {
    const content = String(
      (t.message as Record<string, unknown>).content ||
        (t.message as Record<string, unknown>).result ||
        "",
    );
    return (
      <div className="transcript-card">
        <span className="transcript-label">{"\uD83D\uDD27"} Tool</span>
        <div className="transcript-body">
          <pre>
            {content.length > 500 ? content.slice(0, 500) + "..." : content}
          </pre>
        </div>
      </div>
    );
  }

  // ── Error ────────────────────────────────────
  if (t.kind === TranscriptKind.Error) {
    const content = String(
      (t.message as Record<string, unknown>).message ||
        (t.message as Record<string, unknown>).content ||
        "",
    );
    return (
      <div className="transcript-card error-card">
        <span className="transcript-label">{"\u26A0\uFE0F"} Error</span>
        <div className="transcript-body">{content}</div>
      </div>
    );
  }

  // ── Assistant — render sub-streams ───────────

  // 刷新恢复：subStreams 为空时从 message 重建
  let subStreams = t.subStreams;
  let active = t.activeSubStream;
  if (t.isFlushed && subStreams.length === 0 && !active) {
    subStreams = rebuildFromMessage(t.id, t.message as Record<string, unknown>);
  }

  const all = [
    ...subStreams.map((ss) => ({ ss, active: false })),
    ...(active ? [{ ss: active, active: true }] : []),
  ];

  const plainItems: { ss: SubStream; active: boolean }[] = [];
  const toolItems: { ss: SubStream; active: boolean }[] = [];

  for (const item of all) {
    if (
      item.ss.kind === ChunkKind.ToolName ||
      item.ss.kind === ChunkKind.ToolArguments
    ) {
      toolItems.push(item);
    } else {
      plainItems.push(item);
    }
  }

  const toolCards = groupToolCards(toolItems);

  return (
    <div className="transcript-card assistant-card">
      {plainItems.map(({ ss, active: isActive }, i) => {
        const renderer = chunkRenderers[ss.kind];
        return renderer ? (
          <span key={`${ss.id}-${i}`}>
            {renderer({
              ss,
              active: isActive,
              thinkingState: expandedThinking,
              onToggleThinking: toggleThinking,
            })}
          </span>
        ) : (
          <div key={`${ss.id}-${i}`} className="transcript-body">
            <Markdown text={ss.text} />
          </div>
        );
      })}

      {Array.from(toolCards.entries()).map(([id, g]) => (
        <ToolCard key={id} name={g.name} args={g.args} active={g.active} />
      ))}
    </div>
  );
}
