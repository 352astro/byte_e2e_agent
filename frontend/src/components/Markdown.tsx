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

// ── Pre-marked LaTeX extraction ───────────────────────

/**
 * Extract `$$...$$` and `$...$` blocks *before* marked.parse() so that
 * Markdown syntax (\\, _, etc.) inside math blocks is never corrupted.
 *
 * Block math (`$$`) is extracted first so its `$$` delimiter isn't
 * stolen by the inline `$` pattern.
 */
function extractMathRaw(md: string): {
    text: string;
    blocks: Map<string, { source: string; displayMode: boolean }>;
} {
    const blocks = new Map<string, { source: string; displayMode: boolean }>();
    let idx = 0;

    // Phase 1: block math $$...$$
    let text = md.replace(/\$\$([\s\S]+?)\$\$/g, (_, source: string) => {
        const key = `<!--MATH_RAW_${idx}-->`;
        blocks.set(key, { source: source.trim(), displayMode: true });
        idx++;
        return key;
    });

    // Phase 2: inline math $...$
    // Inline math: must not span lines (GitHub) nor cross table cells (|).
    text = text.replace(/\$([^$\n]+?)\$/g, (match: string, source: string) => {
        if (source.includes("|")) return match;
        const key = `<!--MATH_RAW_${idx}-->`;
        blocks.set(key, { source: source.trim(), displayMode: false });
        idx++;
        return key;
    });

    return { text, blocks };
}

/** Render a single math block (inline or display) with KaTeX. */

/** Wrap <pre> blocks with a copy-button container. */
function addCopyButtons(html: string): string {
    return html.replace(
        /<pre([^>]*)>([\s\S]*?)<\/pre>/g,
        (_, attrs: string, content: string) => {
            // Extract text from inside <code> if present
            let code = content
                .replace(/<\/?[^>]+(>|$)/g, '')  // strip HTML tags
                .replace(/&amp;/g, '&')
                .replace(/&lt;/g, '<')
                .replace(/&gt;/g, '>')
                .replace(/&quot;/g, '"');
            const escapedCode = code
                .replace(/&/g, '&amp;')
                .replace(/"/g, '&quot;');
            return `<div class="code-block-wrapper"><button class="copy-btn" onclick="var t=this;navigator.clipboard.writeText(this.dataset.code).then(function(){t.innerHTML='<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#4caf50\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M20 6L9 17l-5-5\"/></svg>';setTimeout(function(){t.innerHTML='<svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"9\" y=\"9\" width=\"13\" height=\"13\" rx=\"2\" ry=\"2\"/><path d=\"M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1\"/></svg>'},1500)})" data-code="${escapedCode}"><svg width=\"14\" height=\"14\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"9\" y=\"9\" width=\"13\" height=\"13\" rx=\"2\" ry=\"2\"/><path d=\"M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1\"/></svg></button><pre${attrs}>${content}</pre></div>`;
        },
    );
}

function renderKatex(source: string, displayMode: boolean): string {
    try {
        return katex.renderToString(source, {
            displayMode,
            throwOnError: true,
        });
    } catch {
        // On failure return the raw source wrapped as a code block
        const escaped = source
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
        const wrapper = displayMode ? "div" : "span";
        return `<${wrapper} class="katex-error-fallback"><code>${escaped}</code></${wrapper}>`;
    }
}

// ── Public component ──────────────────────────────────

let mermaidIdCounter = 0;

interface MarkdownProps {
    text: string;
}

export default function Markdown({ text }: MarkdownProps) {
    const mountedRef = useRef(true);
    const [html, setHtml] = useState("");

    const { baseHtml, diagrams, mathBlocks } = useMemo(() => {
        if (!text)
            return {
                baseHtml: "",
                diagrams: new Map<string, string>(),
                mathBlocks: new Map<
                    string,
                    { source: string; displayMode: boolean }
                >(),
            };

        const plain = decodeHtmlEntities(text);

        // 1. Extract mermaid
        const { text: afterMermaid, diagrams } = extractMermaidRaw(plain);

        // 2. Extract LaTeX (before marked, so Markdown syntax inside math is safe)
        const { text: md, blocks: mathBlocks } = extractMathRaw(afterMermaid);

        // 3. Markdown → HTML (only on the cleaned text)
        const raw = marked.parse(md, {
            highlight: markedHighlight,
        }) as string;

        // 4. Add copy buttons to code blocks
        let out = addCopyButtons(raw);

        // 5. Render KaTeX into the HTML synchronously
        for (const [key, block] of mathBlocks) {
            out = out.replace(
                key,
                renderKatex(block.source, block.displayMode),
            );
        }

        return { baseHtml: out, diagrams, mathBlocks };
    }, [text]);

    // Mermaid is async, handled in a separate phase
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
                    // Mermaid returns an error SVG on parse failure — detect it
                    if (svg.includes("Syntax error") || svg.includes("mermaid version")) {
                        throw new Error("mermaid parse error");
                    }
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
                } finally {
                    container.remove();
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
