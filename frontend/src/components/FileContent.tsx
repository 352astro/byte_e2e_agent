import Markdown from "./Markdown";
import HighlightCode from "./HighlightCode";

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

interface FileContentProps {
  content: string;
  filePath?: string;
  className?: string;
}

export default function FileContent({
  content,
  filePath = "",
  className = "",
}: FileContentProps) {
  const lang = guessLanguage(filePath);

  // .md files render as formatted markdown, not code
  if (lang === "markdown") {
    return (
      <div className={className}>
        <Markdown text={content} />
      </div>
    );
  }

  if (lang) {
    return (
      <HighlightCode code={content} language={lang} className={className} />
    );
  }

  return (
    <div className={className}>
      <Markdown text={content} />
    </div>
  );
}

export { guessLanguage };
