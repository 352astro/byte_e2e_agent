import { useState, useEffect } from "react";
import Icon from "./Icon";
import CollapsibleCard from "./CollapsibleCard";
import HighlightCode from "./HighlightCode";
import FileContent from "./FileContent";
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
  useEffect(() => { if (defaultCollapsed) setCollapsed(true); }, [defaultCollapsed]);
  const timeoutMs = extractArg(pair.arguments, "timeout_ms");
  const timeout = timeoutMs
    ? String(Math.round(Number(timeoutMs) / 1000))
    : null;
  const command = extractArg(pair.arguments, "command");
  const hasResult = Boolean(pair.result);

  const pairId = `${pair.callTranscriptId}/${pair.callIndex}`;
  return (
    <>
      {/* Call card */}
      <CollapsibleCard
        id={`${pair.callTranscriptId}/shell`}
        dataFid={pairId}
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
        <HighlightCode
          code={command || pair.arguments || "\u2026"}
          language="bash"
          className="shell-call-command"
        />
      </CollapsibleCard>

      {/* Result card */}
      {pair.result && (
        <CollapsibleCard
          id={`${pair.result.id}/result`}
          dataFid={pairId}
          collapsed={collapsed}
          onToggle={() => setCollapsed((p) => !p)}
          cardClassName="tool-card--shell"
        >
          <HighlightCode
            code={String(
              (pair.result.message as Record<string, unknown>).result || "",
            )}
            language="bash"
            className="tool-shell-output"
          />
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
  const filePath = extractArg(pair.arguments, "path") || "";
  const content =
    variant === "Write"
      ? extractArg(pair.arguments, "content") || ""
      : pair.result
        ? String(
            (pair.result.message as Record<string, unknown>).result || "",
          )
        : "";
  const hasContent = Boolean(content);

  const pairId = `${pair.callTranscriptId}/${pair.callIndex}`;
  return (
    <CollapsibleCard
      id={`${pair.callTranscriptId}/${variant.toLowerCase()}`}
      dataFid={pairId}
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
        <FileContent
          content={content}
          filePath={filePath}
          className={variant === "Write" ? "write-call-body" : "read-call-body"}
        />
      )}
    </CollapsibleCard>
  );
}

// ── Default pair: call card + result card ────────────────

function DefaultPair({ pair, defaultCollapsed }: { pair: ToolPair; defaultCollapsed: boolean }) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  useEffect(() => { if (defaultCollapsed) setCollapsed(true); }, [defaultCollapsed]);

  const pairId = `${pair.callTranscriptId}/${pair.callIndex}`;
  return (
    <>
      <CollapsibleCard
        id={`${pair.callTranscriptId}/default`}
        dataFid={pairId}
        collapsed={collapsed}
        onToggle={() => setCollapsed((p) => !p)}
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
          dataFid={pairId}
          collapsed={collapsed}
          onToggle={() => setCollapsed((p) => !p)}
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
