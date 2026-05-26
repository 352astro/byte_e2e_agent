/**
 * Shared tool-card renderers used by TranscriptCard, ToolPairCard, and ToolResult.
 *
 * Each tool type (Shell / Write / Read / default) has a single component that
 * accepts a union of props so the three call-sites can compose them without
 * duplicating markup.
 */

import Icon from "./Icon";
import CollapsibleCard from "./CollapsibleCard";
import HighlightCode from "./HighlightCode";
import FileContent from "./FileContent";
import Markdown from "./Markdown";
import { extractArg } from "../utils";
import { useCollapsible } from "../hooks/useCollapsible";

// ── Shared helpers ─────────────────────────────────────

function shellMeta(args: string) {
    const timeoutMs = extractArg(args, "timeout_ms");
    return {
        command: extractArg(args, "command") || args,
        timeout: timeoutMs
            ? String(Math.round(Number(timeoutMs) / 1000))
            : null,
    };
}

function fileMeta(args: string) {
    return {
        path: extractArg(args, "path") || "",
        content: extractArg(args, "content") || "",
    };
}

// ── Shell ──────────────────────────────────────────────

interface ShellCardProps {
    cardId: string;
    args: string;
    /** When true the card is still streaming — show spinner & timeout. */
    active?: boolean;
    /** Auto-collapse when this flips to true (e.g. streaming finished). */
    defaultCollapsed?: boolean;
    /** Omit the "Run Command" header (used by standalone result cards). */
    standalone?: boolean;
    focusId?: string;
    /** When provided a second card is rendered below the call showing the result. */
    resultContent?: string;
    /** External collapsed control (when parent manages a Set of IDs). */
    collapsed?: boolean;
    onToggle?: (id: string) => void;
}

export function ShellCard({
    cardId,
    args,
    active = false,
    defaultCollapsed = false,
    standalone = false,
    focusId,
    resultContent,
    collapsed: controlledCollapsed,
    onToggle: onToggleControlled,
}: ShellCardProps) {
    const [collapsed, toggle] = useCollapsible(
        defaultCollapsed,
        controlledCollapsed,
        onToggleControlled,
    );
    const { command, timeout } = shellMeta(args);
    const hasResult = resultContent !== undefined;

    return (
        <>
            <CollapsibleCard
                id={`${cardId}/shell`}
                dataFid={focusId}
                collapsed={collapsed}
                onToggle={toggle}
                cardClassName="tool-card--shell"
                headerClassName="shell-call-bar"
                standalone={standalone && !command}
                title={
                    standalone ? undefined : (
                        <>
                            <Icon
                                name="tool"
                                size={13}
                                className="shell-call-icon"
                            />
                            <span className="shell-call-label">
                                Run Command
                            </span>
                        </>
                    )
                }
                headerRight={
                    !hasResult && active ? (
                        <>
                            {timeout && (
                                <span className="shell-call-timeout">
                                    {timeout}s
                                </span>
                            )}
                            <span className="shell-call-spinner" />
                        </>
                    ) : undefined
                }
            >
                <HighlightCode
                    code={command || "\u2026"}
                    language="bash"
                    className="shell-call-command"
                />
            </CollapsibleCard>

            {hasResult && (
                <CollapsibleCard
                    id={`${cardId}/shell-result`}
                    dataFid={focusId}
                    collapsed={collapsed}
                    onToggle={toggle}
                    cardClassName="tool-card--shell"
                    standalone
                >
                    <HighlightCode
                        code={resultContent}
                        language="bash"
                        className="tool-shell-output"
                    />
                </CollapsibleCard>
            )}
        </>
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
    /** File content to display in the body (omitted = no body). */
    bodyContent?: string;
    /** External collapsed control (when parent manages a Set of IDs). */
    collapsed?: boolean;
    onToggle?: (id: string) => void;
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
}: WriteReadCardProps) {
    const [collapsed, toggle] = useCollapsible(
        defaultCollapsed,
        controlledCollapsed,
        onToggleControlled,
    );
    const { path: filePath } = fileMeta(args);
    const hasBody = bodyContent !== undefined;
    const cardClass =
        variant === "Write" ? "tool-card--write" : "tool-card--read";
    const headerClass =
        variant === "Write" ? "write-call-bar" : "read-call-bar";
    const bodyClass =
        variant === "Write" ? "write-call-body" : "read-call-body";

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
                    {filePath && (
                        <span className="write-call-path">{filePath}</span>
                    )}
                </>
            }
        >
            {hasBody && (
                <FileContent
                    content={bodyContent}
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
    /** When provided a second card is rendered below showing the result. */
    resultContent?: string;
    /** External collapsed control (when parent manages a Set of IDs). */
    collapsed?: boolean;
    onToggle?: (id: string) => void;
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
}: DefaultToolCardProps) {
    const [collapsed, toggle] = useCollapsible(
        defaultCollapsed,
        controlledCollapsed,
        onToggleControlled,
    );

    return (
        <>
            <CollapsibleCard
                id={`${cardId}/default`}
                dataFid={focusId}
                collapsed={collapsed}
                onToggle={toggle}
                cardClassName={active ? "tool-card--streaming" : ""}
                title={
                    <>
                        <Icon name="tool" size={13} className="tool-icon" />
                        <span className="tool-label">
                            {toolName || "\u2026"}
                        </span>
                    </>
                }
            >
                <div className="tool-code-block">
                    <pre>
                        <code>{args || "\u2026"}</code>
                    </pre>
                </div>
            </CollapsibleCard>

            {resultContent !== undefined && (
                <CollapsibleCard
                    id={`${cardId}/default-result`}
                    dataFid={focusId}
                    collapsed={collapsed}
                    onToggle={toggle}
                >
                    <div className="tool-code-block">
                        <pre>
                            <code>{resultContent}</code>
                        </pre>
                    </div>
                </CollapsibleCard>
            )}
        </>
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

    // Shell — standalone, no header, terminal output
    if (toolName === "Shell") {
        return (
            <CollapsibleCard
                id="shell-result"
                collapsed={collapsed}
                onToggle={toggle}
                cardClassName="tool-card--shell"
                standalone
            >
                <HighlightCode
                    code={result}
                    language="bash"
                    className="tool-shell-output"
                />
            </CollapsibleCard>
        );
    }

    // Read — file content with language detection
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
                        <Icon
                            name="write"
                            size={13}
                            className="tool-file-icon"
                        />
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

    // Write & everything else — Markdown body
    return (
        <CollapsibleCard
            id={`${toolName}-result`}
            collapsed={collapsed}
            onToggle={toggle}
            headerClassName="tool-default-header"
            title={
                <>
                    <Icon name="tool" size={13} className="tool-default-icon" />
                    <span className="tool-default-label">{toolName}</span>
                </>
            }
        >
            <div className="tool-default-body">
                <Markdown text={result} />
            </div>
        </CollapsibleCard>
    );
}
