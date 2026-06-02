/**
 * Extract a top-level key from a JSON string (or JSON-like string).
 * Returns null when the key is not found or parsing fails.
 */
export function extractArg(args: string, key: string): string | null {
    try {
        const obj = JSON.parse(args);
        return obj[key] != null ? String(obj[key]) : null;
    } catch {
        const re = new RegExp(
            `"${key}"\\s*:\\s*("(?:[^"\\\\]|\\\\.)*"|\\d+(?:\\.\\d+)?)`,
            "s",
        );
        const m = args.match(re);
        if (!m) return null;
        let v = m[1];
        if (v.startsWith('"')) v = v.slice(1, -1).replace(/\\"/g, '"');
        return v;
    }
}

// ── Partial-JSON splitting for streaming arguments ──────

/**
 * Unescape a JSON string literal.
 * Delegates to native JSON.parse — correct, fast, zero maintenance.
 *
 * The only case JSON.parse cannot handle is a trailing lone backslash
 * (escape split across two chunks).  We strip it, parse the rest, then
 * re-append so the next chunk can complete it.
 */
function jsonUnescape(s: string): string {
    try {
        return JSON.parse(`"${s}"`);
    } catch {
        if (s.endsWith("\\")) {
            const safe = s.slice(0, -1);
            try {
                return JSON.parse(`"${safe}"`) + "\\";
            } catch {
                /* give up, return raw */
            }
        }
        return s;
    }
}

/**
 * Which JSON key carries the long, streaming value for each tool.
 * The backend guarantees short fields are serialised *before* this key.
 */
const TOOL_LONG_KEY: Record<string, string> = {
    Shell: "command",
    Write: "content",
};

export interface SplitResult {
    /** Parsed short fields (everything before the long key). */
    meta: Record<string, unknown>;
    /** Unescaped, potentially incomplete value of the long key. */
    rest: string;
}

/**
 * Split a partially-streamed JSON arguments string into finished short
 * fields and the still-incomplete long value.
 *
 * Relies on the backend placing short fields first so the prefix is
 * always parseable by the time the first chunk arrives.
 */
export function splitPartialJson(raw: string, longKey: string): SplitResult {
    const empty: SplitResult = { meta: {}, rest: "" };
    if (!raw) return empty;

    // Best case: the whole string is already valid JSON
    try {
        const parsed = JSON.parse(raw);
        if (
            parsed &&
            typeof parsed === "object" &&
            !Array.isArray(parsed) &&
            Object.prototype.hasOwnProperty.call(parsed, longKey)
        ) {
            const { [longKey]: longValue, ...meta } = parsed as Record<
                string,
                unknown
            >;
            return {
                meta,
                rest: longValue != null ? String(longValue) : "",
            };
        }
        return { meta: parsed, rest: "" };
    } catch {
        /* fall through */
    }

    // Locate the long key
    const keyToken = `"${longKey}"`;
    const keyPos = raw.indexOf(keyToken);
    if (keyPos === -1) {
        try {
            return { meta: JSON.parse(raw.trimEnd() + "}"), rest: "" };
        } catch {
            return { meta: {}, rest: "" };
        }
    }

    // Skip past the key and colon to the value
    const afterKey = raw.slice(keyPos + keyToken.length);
    const colonMatch = afterKey.match(/^\s*:\s*/);
    if (!colonMatch) return empty;

    const afterColon = afterKey.slice(colonMatch[0].length);
    if (!afterColon.startsWith('"')) return empty; // non-string value

    // Build prefix JSON: everything before the long key, minus trailing comma
    let prefix = raw.slice(0, keyPos).trimEnd();
    if (prefix.endsWith(",")) prefix = prefix.slice(0, -1).trimEnd();

    let meta: Record<string, unknown> = {};
    try {
        meta = JSON.parse(prefix + "}");
    } catch {
        /* prefix may be unparseable — return empty meta */
    }

    // The raw JSON-encoded value after the opening quote
    const rawValue = afterColon.slice(1);

    return { meta, rest: jsonUnescape(rawValue) };
}

/**
 * Convenience wrapper: split arguments for a known tool type.
 * Falls back to full parse / raw for tools without a declared long key.
 */
export function extractToolMeta(raw: string, toolName: string): SplitResult {
    const longKey = TOOL_LONG_KEY[toolName];
    if (longKey) {
        return splitPartialJson(raw, longKey);
    }
    try {
        return { meta: JSON.parse(raw), rest: "" };
    } catch {
        return { meta: {}, rest: raw };
    }
}
