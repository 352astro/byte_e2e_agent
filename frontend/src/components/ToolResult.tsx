import { useState, useCallback } from "react";
import Markdown from "./Markdown";
import Icon from "./Icon";
import CollapsibleCard from "./CollapsibleCard";

// ── Helpers ──────────────────────────────────────────────

function guessLanguage(filePath: string): string {
  const ext = filePath.split(".").pop()?.toLowerCase() || "";
  const map: Record<string, string> = {
    ts: "typescript",
    tsx: "tsx",
    js: "javascript",
    jsx: "jsx",
    py: "python",
    rs: "rust",
    go: "go",
    java: "java",
    c: "c",
    cpp: "cpp",
    h: "c",
    hpp: "cpp",
    css: "css",
    html: "html",
    json: "json",
    yaml: "yaml",
    yml: "yaml",
    toml: "toml",
    md: "markdown",
    sh: "bash",
    bash: "bash",
    zsh: "bash",
    sql: "sql",
    xml: "xml",
    svg: "svg",
  };
  return map[ext] || "";
}

interface ToolResultProps {
  toolName: string;
  result: string;
  toolArgs?: Record<string, unknown>;
}

// ── Shell — no header, dark terminal output ──────────────

function ShellResult({ result, toolArgs }: ToolResultProps) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <CollapsibleCard
      id="shell-result"
      collapsed={collapsed}
      onToggle={() => setCollapsed((p) => !p)}
      cardClassName="tool-card--shell"
    >
      <pre className="tool-shell-output">
        <code>{result}</code>
      </pre>
    </CollapsibleCard>
  );
}

// ── Write / Read — file content with language detection ──

function FileContentResult({ toolName, result, toolArgs }: ToolResultProps) {
  const [collapsed, setCollapsed] = useState(false);
  const filePath = toolArgs?.path ? String(toolArgs.path) : "";
  const lang = guessLanguage(filePath);
  // Read: content is the result itself. Write: content comes from args.
  const displayContent = result || "";
  return (
    <CollapsibleCard
      id={`${toolName}-result`}
      collapsed={collapsed}
      onToggle={() => setCollapsed((p) => !p)}
      cardClassName="tool-card--file"
      headerClassName="tool-file-header"
      title={
        <>
          <Icon name="write" size={13} className="tool-file-icon" />
          <span className="tool-file-label">{toolName}</span>
        </>
      }
    >
      {lang ? (
        <pre className="tool-file-code">
          <code className={`language-${lang}`}>{displayContent}</code>
        </pre>
      ) : (
        <div className="tool-file-md">
          <Markdown text={displayContent} />
        </div>
      )}
    </CollapsibleCard>
  );
}

// ── Default ──────────────────────────────────────────────

function DefaultResult({ toolName, result }: ToolResultProps) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <CollapsibleCard
      id={`${toolName}-result`}
      collapsed={collapsed}
      onToggle={() => setCollapsed((p) => !p)}
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

// ── Public ───────────────────────────────────────────────

export default function ToolResult({
  toolName,
  result,
  toolArgs,
}: ToolResultProps) {
  switch (toolName) {
    case "Shell":
      return (
        <ShellResult toolName={toolName} result={result} toolArgs={toolArgs} />
      );
    case "Write":
    case "Read":
      return (
        <FileContentResult
          toolName={toolName}
          result={result}
          toolArgs={toolArgs}
        />
      );
    default:
      return (
        <DefaultResult
          toolName={toolName}
          result={result}
          toolArgs={toolArgs}
        />
      );
  }
}
