import { useMemo } from "react";
import { highlightCode } from "../hooks/highlight";
import CopyButton from "./CopyButton";

interface HighlightCodeProps {
  code: string;
  language?: string;
  className?: string;
}

export default function HighlightCode({
  code,
  language,
  className = "",
}: HighlightCodeProps) {
  const html = useMemo(() => highlightCode(code, language), [code, language]);

  return (
    <div className="code-block-wrapper">
      <CopyButton text={code} />
      <pre className={className}>
        <code dangerouslySetInnerHTML={{ __html: html }} />
      </pre>
    </div>
  );
}
