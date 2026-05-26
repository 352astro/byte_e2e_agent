import { useState } from "react";
import Icon from "./Icon";
import CollapsibleCard from "./CollapsibleCard";
import HighlightCode from "./HighlightCode";
import FileContent from "./FileContent";
import Markdown from "./Markdown";


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

// ── Write / Read — file content with language detection ──

function FileContentResult({ toolName, result, toolArgs }: ToolResultProps) {
  const [collapsed, setCollapsed] = useState(false);
  const filePath = toolArgs?.path ? String(toolArgs.path) : "";
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
      <FileContent
        content={displayContent}
        filePath={filePath}
        className="tool-file-md"
      />
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
      return (
        <DefaultResult
          toolName={toolName}
          result={result}
          toolArgs={toolArgs}
        />
      );
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
