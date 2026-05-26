import { useState, useEffect, useMemo, useRef } from "react";
import { marked } from "marked";
import katex from "katex";
import "katex/dist/katex.min.css";
import mermaid from "mermaid";
import { markedHighlight } from "../hooks/highlight";

// ── One-time mermaid init ──────────────────────────────

mermaid.initialize({ startOnLoad: false, securityLevel: "loose" });

// ── Helpers ────────────────────────────────────────────

const HTML_ENTITIES: Record<string, string> = {
    "&gt;": ">",
    "&lt;": "<",
    "&quot;": '"',
    "&amp;": "&",
    "&apos;": "'",
    "&nbsp;": "\u00A0",
};

function decodeHtmlEntities(text: string): string {
    return text.replace(
        /&(?:gt|lt|quot|amp|apos|nbsp|#\d+|#x[0-9a-fA-F]+);/g,
        (entity) => {
            if (HTML_ENTITIES[entity]) return HTML_ENTITIES[entity];
            if (entity.startsWith("&#x") || entity.startsWith("&#X")) {
                return String.fromCharCode(parseInt(entity.slice(3, -1), 16));
            }
            if (entity.startsWith("&#")) {
                return String.fromCharCode(parseInt(entity.slice(2, -1), 10));
            }
            return entity;
        },
    );
}

function extractMermaidRaw(md: string): {
    text: string;
    diagrams: Map<string, string>;
} {
    const diagrams = new Map<string, string>();
    let idx = 0;

    const text = md.replace(
        /```mermaid\n([\s\S]*?)```/g,
        (_, source: string) => {
            const key = `<!--MERMAID_RAW_${idx}-->`;
            diagrams.set(key, source.trim());
            idx++;
            return key;
        },
    );

    return { text, diagrams };
}

// ── LaTeX rendering (synchronous) ──────────────────────

/** Shared regex guard: match code blocks so they pass through untouched. */
const CODE_GUARD = /<pre[^>]*>[\s\S]*?<\/pre>|<code[^>]*>[\s\S]*?<\/code>/;

/** Build a single-pass KaTeX replacer for a given math pattern + display mode. */
function katexReplace(
    mathPattern: RegExp,
    displayMode: boolean,
): (html: string) => string {
    const re = new RegExp(CODE_GUARD.source + "|" + mathPattern.source, "g");
    return (html) =>
        html.replace(re, (match, ...args) => {
            if (match.startsWith("<")) return match; // code block
            const math = args[0] as string | undefined;
            if (!math) return match;
            try {
                return katex.renderToString(math, {
                    displayMode,
                    throwOnError: false,
                });
            } catch {
                return match;
            }
        });
}

const replaceBlockMath = katexReplace(/\$\$([\s\S]+?)\$\$/, true);
const replaceInlineMath = katexReplace(/\$([^$]+?)\$/, false);

/** Block first — otherwise inline `$` would steal the opening `$$`. */
function renderMath(html: string): string {
    return replaceInlineMath(replaceBlockMath(html));
}

// ── Public component ──────────────────────────────────

let mermaidIdCounter = 0;

interface MarkdownProps {
    text: string;
}

export default function Markdown({ text }: MarkdownProps) {
    const mountedRef = useRef(true);
    const [html, setHtml] = useState("");

    const { baseHtml, diagrams } = useMemo(() => {
        if (!text) return { baseHtml: "", diagrams: new Map<string, string>() };

        const plain = decodeHtmlEntities(text);
        const { text: md, diagrams } = extractMermaidRaw(plain);
        const raw = marked.parse(md, {
            highlight: markedHighlight,
        }) as string;

        return { baseHtml: renderMath(raw), diagrams };
    }, [text]);

    useEffect(() => {
        mountedRef.current = true;

        if (diagrams.size === 0) {
            setHtml(baseHtml);
            return;
        }

        const entries = Array.from(diagrams.entries());

        Promise.allSettled(
            entries.map(async ([placeholder, source]) => {
                const id = `mermaid-${mermaidIdCounter++}`;
                try {
                    const { svg } = await mermaid.render(id, source);
                    return { placeholder, html: svg };
                } catch {
                    const escaped = source
                        .replace(/&/g, "&amp;")
                        .replace(/</g, "&lt;")
                        .replace(/>/g, "&gt;");
                    return {
                        placeholder,
                        html: `<pre class="mermaid-error"><code>${escaped}</code></pre>`,
                    };
                }
            }),
        ).then((results) => {
            if (!mountedRef.current) return;
            let out = baseHtml;
            for (const r of results) {
                if (r.status === "fulfilled") {
                    out = out.replace(r.value.placeholder, r.value.html);
                }
            }
            setHtml(out);
        });

        return () => {
            mountedRef.current = false;
        };
    }, [baseHtml, diagrams]);

    return (
        <div
            className="md-content"
            dangerouslySetInnerHTML={{ __html: html }}
        />
    );
}
