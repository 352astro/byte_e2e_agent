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
