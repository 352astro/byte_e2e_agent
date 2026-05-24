import { useMemo } from "react";
import { marked } from "marked";
import { markedHighlight } from "../hooks/highlight";

interface MarkdownProps {
  text: string;
}

export default function Markdown({ text }: MarkdownProps) {
  const html = useMemo(() => {
    if (!text) return "";
    return marked.parse(text, {
      highlight: markedHighlight,
    }) as string;
  }, [text]);

  return (
    <div className="md-content" dangerouslySetInnerHTML={{ __html: html }} />
  );
}
