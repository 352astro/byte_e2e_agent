import { useState, useEffect } from "react";
import Markdown from "./Markdown";
import Icon from "./Icon";
import CollapsibleCard from "./CollapsibleCard";
import type { ToolPair } from "../types";

// ── Helpers ──────────────────────────────────────────────

function extractArg(args: string, key: string): string | null {
  try {
    const obj = JSON.parse(args);
    return obj[key] != null ? String(obj[key]) : null;
  } catch {
    const re = new RegExp(
      `"${key}"\\s*:\\s*("(?:[^"\\\\]|\\\\.)*"|\\d+(?:\\.\\d+)?)`,
      "s",
    );
    const m = args.match(re);
    if (!m) return null;
    let v = m[1];
    if (v.startsWith('"')) v = v.slice(1, -1).replace(/\\"/g, '"');
    return v;
  }
}

// ── Shell pair: call card + result card ──────────────────

function ShellPair({ pair, defaultCollapsed }: { pair: ToolPair; defaultCollapsed: boolean }) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const [resultCollapsed, setResultCollapsed] = useState(false);
  useEffect(() => { if (defaultCollapsed) setCollapsed(true); }, [defaultCollapsed]);
  const timeoutMs = extractArg(pair.arguments, "timeout_ms");
  const timeout = timeoutMs
    ? String(Math.round(Number(timeoutMs) / 1000))
    : null;
  const command = extractArg(pair.arguments, "command");
  const hasResult = Boolean(pair.result);

  return (
    <>
      {/* Call card */}
      <CollapsibleCard
        id={`${pair.callTranscriptId}/shell`}
        collapsed={collapsed}
        onToggle={() => setCollapsed((p) => !p)}
        cardClassName="tool-card--shell"
        headerClassName="shell-call-bar"
        title={
          <>
            <Icon name="tool" size={13} className="shell-call-icon" />
            <span className="shell-call-label">Run Command</span>
          </>
        }
        headerRight={
          !hasResult ? (
            <>
              {timeout && <span className="shell-call-timeout">{timeout}s</span>}
              <span className="shell-call-spinner" />
            </>
          ) : undefined
        }
      >
        <pre className="shell-call-command">
          <code>{command || pair.arguments || "\u2026"}</code>
        </pre>
      </CollapsibleCard>

      {/* Result card */}
      {pair.result && (
        <CollapsibleCard
          id={`${pair.result.id}/result`}
          collapsed={resultCollapsed}
          onToggle={() => setResultCollapsed((p) => !p)}
          cardClassName="tool-card--shell"
        >
          <pre className="tool-shell-output">
            <code>
              {String(
                (pair.result.message as Record<string, unknown>).result || "",
              )}
            </code>
          </pre>
        </CollapsibleCard>
      )}
    </>
  );
}

// ── Read / Write merged card ─────────────────────────────

function ReadWritePair({
  pair,
  variant,
  defaultCollapsed,
}: {
  pair: ToolPair;
  variant: "Write" | "Read";
  defaultCollapsed: boolean;
}) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  useEffect(() => { if (defaultCollapsed) setCollapsed(true); }, [defaultCollapsed]);
  const filePath = extractArg(pair.arguments, "path");
  const content =
    variant === "Write"
      ? extractArg(pair.arguments, "content")
      : pair.result
        ? String(
            (pair.result.message as Record<string, unknown>).result || "",
          )
        : "";
  const hasContent = Boolean(content);

  return (
    <CollapsibleCard
      id={`${pair.callTranscriptId}/${variant.toLowerCase()}`}
      collapsed={collapsed}
      onToggle={() => setCollapsed((p) => !p)}
      cardClassName={
        variant === "Write" ? "tool-card--write" : "tool-card--read"
      }
      headerClassName={
        variant === "Write" ? "write-call-bar" : "read-call-bar"
      }
      title={
        <>
          <Icon name="write" size={13} className="write-call-icon" />
          <span className="write-call-label">{variant}</span>
          {filePath && <span className="write-call-path">{filePath}</span>}
        </>
      }
    >
      {hasContent && (
        <div className={variant === "Write" ? "write-call-body" : "read-call-body"}>
          <Markdown text={content || "\u2026"} />
        </div>
      )}
    </CollapsibleCard>
  );
}

// ── Default pair: call card + result card ────────────────

function DefaultPair({ pair, defaultCollapsed }: { pair: ToolPair; defaultCollapsed: boolean }) {
  const [callCollapsed, setCallCollapsed] = useState(defaultCollapsed);
  const [resultCollapsed, setResultCollapsed] = useState(defaultCollapsed);
  useEffect(() => { if (defaultCollapsed) { setCallCollapsed(true); setResultCollapsed(true); } }, [defaultCollapsed]);

  return (
    <>
      <CollapsibleCard
        id={`${pair.callTranscriptId}/default`}
        collapsed={callCollapsed}
        onToggle={() => setCallCollapsed((p) => !p)}
        title={
          <>
            <Icon name="tool" size={13} className="tool-icon" />
            <span className="tool-label">{pair.toolName}</span>
          </>
        }
      >
        <div className="tool-code-block">
          <pre>
            <code>{pair.arguments || "\u2026"}</code>
          </pre>
        </div>
      </CollapsibleCard>

      {pair.result && (
        <CollapsibleCard
          id={`${pair.result.id}/result`}
          collapsed={resultCollapsed}
          onToggle={() => setResultCollapsed((p) => !p)}
          title={
            <>
              <Icon name="tool" size={13} className="tool-icon" />
              <span className="tool-label">Result</span>
            </>
          }
        >
          <div className="tool-code-block">
            <pre>
              <code>
                {String(
                  (pair.result.message as Record<string, unknown>).result ||
                    "",
                )}
              </code>
            </pre>
          </div>
        </CollapsibleCard>
      )}
    </>
  );
}

// ── Public ───────────────────────────────────────────────

interface ToolPairCardProps {
  pair: ToolPair;
  defaultCollapsed?: boolean;
}

export default function ToolPairCard({ pair, defaultCollapsed = false }: ToolPairCardProps) {
  switch (pair.toolName) {
    case "Shell":
      return <ShellPair pair={pair} defaultCollapsed={defaultCollapsed} />;
    case "Write":
      return <ReadWritePair pair={pair} variant="Write" defaultCollapsed={defaultCollapsed} />;
    case "Read":
      return <ReadWritePair pair={pair} variant="Read" defaultCollapsed={defaultCollapsed} />;
    default:
      return <DefaultPair pair={pair} defaultCollapsed={defaultCollapsed} />;
  }
}
