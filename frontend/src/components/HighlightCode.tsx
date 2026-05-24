import { useMemo } from "react";
import { highlightCode } from "../hooks/highlight";

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
  const html = useMemo(
    () => highlightCode(code, language),
    [code, language],
  );

  return (
    <pre className={className}>
      <code dangerouslySetInnerHTML={{ __html: html }} />
    </pre>
  );
}
