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
    path: (meta.path as string) || "",
    content: rest || (meta.content as string) || "",
  };
}

/**
 * Build the right-side status indicator: spinner (running), red X (error),
 * green check (completed), plus dim timeout text when applicable.
 */
function buildHeaderRight(
  active: boolean,
  timeout: string | null,
  hasResult: boolean,
): React.ReactNode {
  // unpaired → spinner (backend will eventually pair it)
  // paired   → check (success) or error (when backend provides flag)
  const showSpinner = active || !hasResult;
  return (
    <>
      {timeout && <span className="shell-call-timeout">{timeout}s</span>}
      {showSpinner ? (
        <span className="shell-call-spinner" />
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
          <Icon name="tool" size={13} className="shell-call-icon" />
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

  const cardClass =
    variant === "Write" ? "tool-card--write" : "tool-card--read";
  const headerClass = variant === "Write" ? "write-call-bar" : "read-call-bar";
  const bodyClass = variant === "Write" ? "write-call-body" : "read-call-body";

  return (
    <CollapsibleCard
      id={cardId}
      dataFid={focusId}
      collapsed={collapsed}
      onToggle={toggle}
      cardClassName={`${cardClass}${active ? " tool-card--streaming" : ""}`}
      headerClassName={headerClass}
      title={
        <>
          <Icon name="write" size={13} className="write-call-icon" />
          <span className="write-call-label">{variant}</span>
          {subtitle}
        </>
      }
      headerRight={headerRight}
    >
      {hasBody && (
        <FileContent
          content={displayContent}
          filePath={filePath}
          className={bodyClass}
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
