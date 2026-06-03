/**
 * Shared tool-card renderers used by MessageCard, ToolPairCard, and ToolResult.
 *
 * Each tool type (Shell / Write / Read / default) has a single component that
 * accepts a union of props so the three call-sites can compose them without
 * duplicating markup.
 */

import Icon from "./Icon";
import CollapsibleCard from "./CollapsibleCard";
import HighlightCode from "./HighlightCode";
import FileContent from "./FileContent";
import { extractArg, extractToolMeta } from "../utils";
import { useCollapsible } from "../hooks/useCollapsible";

// ── Shared helpers ─────────────────────────────────────

function shellMeta(args: string) {
  const { meta, rest } = extractToolMeta(args, "Shell");
  const timeoutMs = meta.timeout_ms != null ? String(meta.timeout_ms) : null;
  return {
    command: rest || (meta.command as string) || args,
    timeout: timeoutMs ? String(Math.round(Number(timeoutMs) / 1000)) : null,
  };
}

function fileMeta(args: string) {
  const { meta, rest } = extractToolMeta(args, "Write");
  return {
    path: (meta.path as string) || extractArg(args, "path") || "",
    content: rest || (meta.content as string) || "",
  };
}

function statusLabel(
  status: string | undefined,
  source: string | undefined,
  reason: string | undefined,
): string {
  if (status === "denied") {
    if (source === "user") return "Rejected";
    if (source === "permission") return "Permission denied";
    if (source === "kernel") return "Kernel denied";
    if (source === "sandbox") return "Sandbox denied";
    return reason || "Denied";
  }
  if (status === "timeout") return "Timeout";
  if (status === "interrupted") return "Interrupted";
  if (status === "error") return reason || "Error";
  return "";
}

/**
 * Build the right-side status indicator from explicit tool result status.
 */
function buildHeaderRight(
  active: boolean,
  timeout: string | null,
  hasResult: boolean,
  toolStatus?: string,
  toolStatusSource?: string,
  toolStatusReason?: string,
): React.ReactNode {
  const showSpinner = active || !hasResult;
  const status = toolStatus || (hasResult ? "success" : "");
  const failed = ["denied", "error", "timeout", "interrupted"].includes(status);
  const label = statusLabel(status, toolStatusSource, toolStatusReason);
  return (
    <>
      {timeout && <span className="shell-call-timeout">{timeout}s</span>}
      {showSpinner ? (
        <span className="shell-call-spinner" />
      ) : failed ? (
        <>
          {label && (
            <span className="tool-status-label" title={toolStatusReason || label}>
              {label}
            </span>
          )}
          <Icon name="x" size={12} className="tool-status-err" />
        </>
      ) : (
        <Icon name="check" size={12} className="tool-status-ok" />
      )}
    </>
  );
}

// ── Shell ──────────────────────────────────────────────

interface ShellCardProps {
  cardId: string;
  args: string;
  active?: boolean;
  defaultCollapsed?: boolean;
  focusId?: string;
  resultContent?: string;
  collapsed?: boolean;
  onToggle?: (id: string) => void;
  /** Left extension — rendered after the main label. */
  subtitle?: React.ReactNode;
  /** Right extension — spinner, timeout, etc. */
  headerRight?: React.ReactNode;
}

export function ShellCard({
  cardId,
  args,
  active = false,
  defaultCollapsed = false,
  focusId,
  resultContent,
  collapsed: controlledCollapsed,
  onToggle: onToggleControlled,
  subtitle,
  headerRight,
}: ShellCardProps) {
  const [collapsed, toggle] = useCollapsible(
    defaultCollapsed,
    controlledCollapsed,
    onToggleControlled,
  );
  const { command, timeout } = shellMeta(args);
  const hasResult = resultContent !== undefined;

  return (
    <CollapsibleCard
      id={`${cardId}/shell`}
      dataFid={focusId}
      collapsed={collapsed}
      onToggle={toggle}
      cardClassName="tool-card--shell"
      headerClassName="shell-call-bar"
      title={
        <>
          <Icon name="terminal" size={14} className="shell-call-icon" />
          <span className="shell-call-label">Run Command</span>
          {subtitle}
        </>
      }
      headerRight={headerRight}
    >
      <div className="tool-paired-body tool-paired-body--shell">
        <HighlightCode
          code={command || "\u2026"}
          language="bash"
          className="shell-call-command"
        />
        {hasResult && (
          <HighlightCode
            code={resultContent}
            language="bash"
            className="tool-shell-output"
          />
        )}
      </div>
    </CollapsibleCard>
  );
}

// ── Write / Read ───────────────────────────────────────

interface WriteReadCardProps {
  cardId: string;
  args: string;
  variant: "Write" | "Read";
  active?: boolean;
  defaultCollapsed?: boolean;
  focusId?: string;
  bodyContent?: string;
  collapsed?: boolean;
  onToggle?: (id: string) => void;
  /** Left extension — rendered after the variant label. */
  subtitle?: React.ReactNode;
  /** Right extension — spinner, timeout, etc. */
  headerRight?: React.ReactNode;
}

export function WriteReadCard({
  cardId,
  args,
  variant,
  active = false,
  defaultCollapsed = false,
  focusId,
  bodyContent,
  collapsed: controlledCollapsed,
  onToggle: onToggleControlled,
  subtitle,
  headerRight,
}: WriteReadCardProps) {
  const [collapsed, toggle] = useCollapsible(
    defaultCollapsed,
    controlledCollapsed,
    onToggleControlled,
  );
  const { path: filePath, content: streamingContent } = fileMeta(args);

  const displayContent =
    bodyContent ?? (active ? streamingContent || undefined : undefined);
  const hasBody = displayContent !== undefined;

  const variantClass =
    variant === "Write" ? "file-call--write" : "file-call--read";
  const cardClass =
    variant === "Write" ? "tool-card--write" : "tool-card--read";

  return (
    <CollapsibleCard
      id={cardId}
      dataFid={focusId}
      collapsed={collapsed}
      onToggle={toggle}
      cardClassName={`${cardClass}${active ? " tool-card--streaming" : ""}`}
      headerClassName={`file-call-bar ${variantClass}`}
      title={
        <>
          <Icon
            name={variant === "Read" ? "book-open" : "write"}
            size={variant === "Read" ? 15 : 13}
            className="file-call-icon"
          />
          <span className="file-call-label">{variant}</span>
          {subtitle}
        </>
      }
      headerRight={headerRight}
    >
      {hasBody && (
        <FileContent
          content={displayContent}
          filePath={filePath}
          className={`file-call-body ${variantClass}`}
        />
      )}
    </CollapsibleCard>
  );
}

// ── Default / generic tool ─────────────────────────────

interface DefaultToolCardProps {
  cardId: string;
  toolName: string;
  args: string;
  active?: boolean;
  defaultCollapsed?: boolean;
  focusId?: string;
  resultContent?: string;
  collapsed?: boolean;
  onToggle?: (id: string) => void;
  /** Left extension — rendered after the tool name. */
  subtitle?: React.ReactNode;
  /** Right extension — spinner, timeout, etc. */
  headerRight?: React.ReactNode;
}

export function DefaultToolCard({
  cardId,
  toolName,
  args,
  active = false,
  defaultCollapsed = false,
  focusId,
  resultContent,
  collapsed: controlledCollapsed,
  onToggle: onToggleControlled,
  subtitle,
  headerRight,
}: DefaultToolCardProps) {
  const [collapsed, toggle] = useCollapsible(
    defaultCollapsed,
    controlledCollapsed,
    onToggleControlled,
  );

  return (
    <CollapsibleCard
      id={`${cardId}/default`}
      dataFid={focusId}
      collapsed={collapsed}
      onToggle={toggle}
      cardClassName={active ? "tool-card--streaming" : ""}
      title={
        <>
          <Icon name="tool" size={13} className="tool-icon" />
          <span className="tool-label">{toolName || "\u2026"}</span>
          {subtitle}
        </>
      }
      headerRight={headerRight}
    >
      <div className="tool-paired-body">
        <div className="tool-code-block">
          <pre>
            <code>{args || "\u2026"}</code>
          </pre>
        </div>
        {resultContent !== undefined && (
          <div className="tool-code-block">
            <pre>
              <code>{resultContent}</code>
            </pre>
          </div>
        )}
      </div>
    </CollapsibleCard>
  );
}

// ── Result-only card (used by ToolResult for non-streaming) ─

interface ToolResultCardProps {
  toolName: string;
  result: string;
  toolArgs?: Record<string, unknown>;
}

export function ToolResultCard({
  toolName,
  result,
  toolArgs,
}: ToolResultCardProps) {
  const [collapsed, toggle] = useCollapsible(false);

  if (toolName === "Shell") {
    return (
      <CollapsibleCard
        id="shell-result"
        collapsed={collapsed}
        onToggle={toggle}
        cardClassName="tool-card--shell"
      >
        <HighlightCode
          code={result}
          language="bash"
          className="tool-shell-output"
        />
      </CollapsibleCard>
    );
  }

  if (toolName === "Read") {
    const filePath = toolArgs?.path ? String(toolArgs.path) : "";
    return (
      <CollapsibleCard
        id="read-result"
        collapsed={collapsed}
        onToggle={toggle}
        cardClassName="tool-card--file"
        headerClassName="tool-file-header"
        title={
          <>
            <Icon name="write" size={13} className="tool-file-icon" />
            <span className="tool-file-label">{toolName}</span>
          </>
        }
      >
        <FileContent
          content={result || ""}
          filePath={filePath}
          className="tool-file-md"
        />
      </CollapsibleCard>
    );
  }

  return (
    <CollapsibleCard
      id={`${toolName}-result`}
      collapsed={collapsed}
      onToggle={toggle}
      title={
        <>
          <Icon name="tool" size={13} className="tool-icon" />
          <span className="tool-label">{toolName}</span>
        </>
      }
    >
      <div className="tool-paired-body">
        <div className="tool-code-block">
          <pre>
            <code>{result || "\u2026"}</code>
          </pre>
        </div>
      </div>
    </CollapsibleCard>
  );
}

// ═══════════════════════════════════════════════════════════
//  Unified dispatch
// ═══════════════════════════════════════════════════════════

export interface ToolCardDatum {
  id: string;
  toolName: string;
  args: string;
  active?: boolean;
  collapsed?: boolean;
  onToggle?: (id: string) => void;
  defaultCollapsed?: boolean;
  resultContent?: string;
  bodyContent?: string;
  focusId?: string;
  subtitle?: React.ReactNode;
  toolStatus?: string;
  toolStatusSource?: string;
  toolStatusReason?: string;
}

export function renderToolCard(d: ToolCardDatum) {
  const external = d.collapsed !== undefined;
  const collapsed = external ? d.collapsed : undefined;
  const onToggle = external ? d.onToggle : undefined;
  const defaultCollapsed = external ? false : (d.defaultCollapsed ?? false);

  // ── Left extension is chosen by the caller ──
  const { meta } = extractToolMeta(d.args, d.toolName);
  const subtitle = d.subtitle;

  // ── Compute right-side: spinner + timeout ──
  const timeoutMs = meta.timeout_ms != null ? String(meta.timeout_ms) : null;
  const timeout = timeoutMs
    ? String(Math.round(Number(timeoutMs) / 1000))
    : null;
  const headerRight = buildHeaderRight(
    d.active ?? false,
    timeout,
    d.resultContent !== undefined,
    d.toolStatus,
    d.toolStatusSource,
    d.toolStatusReason,
  );

  switch (d.toolName) {
    case "Shell":
      return (
        <ShellCard
          cardId={d.id}
          args={d.args}
          active={d.active}
          collapsed={collapsed}
          onToggle={onToggle}
          defaultCollapsed={defaultCollapsed}
          focusId={d.focusId}
          resultContent={d.resultContent}
          subtitle={subtitle}
          headerRight={headerRight}
        />
      );
    case "Write":
      return (
        <WriteReadCard
          cardId={d.id}
          args={d.args}
          variant="Write"
          active={d.active}
          collapsed={collapsed}
          onToggle={onToggle}
          defaultCollapsed={defaultCollapsed}
          focusId={d.focusId}
          bodyContent={d.bodyContent}
          subtitle={subtitle}
          headerRight={headerRight}
        />
      );
    case "Read":
      return (
        <WriteReadCard
          cardId={d.id}
          args={d.args}
          variant="Read"
          active={d.active}
          collapsed={collapsed}
          onToggle={onToggle}
          defaultCollapsed={defaultCollapsed}
          focusId={d.focusId}
          bodyContent={d.resultContent ?? d.bodyContent}
          subtitle={subtitle}
          headerRight={headerRight}
        />
      );
    default:
      return (
        <DefaultToolCard
          cardId={d.id}
          toolName={d.toolName}
          args={d.args}
          active={d.active}
          collapsed={collapsed}
          onToggle={onToggle}
          defaultCollapsed={defaultCollapsed}
          focusId={d.focusId}
          resultContent={d.resultContent}
          subtitle={subtitle}
          headerRight={headerRight}
        />
      );
  }
}
