import React, { useEffect, useState } from "react";
import "./TokenBubble.css";

interface TokenBubbleProps {
  usage?: Record<string, unknown>;
  messageId?: string;
}

interface CallItem {
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  reasoning_tokens: number | null;
  prompt_cached_tokens: number | null;
  prompt_cache_hit: number | null;
  prompt_cache_miss: number | null;
  cost_yuan: number | null;
}

function num(v: unknown): number | undefined {
  if (typeof v === "number") return v;
  return undefined;
}

function fmt(n: number | undefined): string {
  if (n === undefined) return "—";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "k";
  return String(n);
}

function hasUsageFields(v: Record<string, unknown> | undefined): boolean {
  if (!v) return false;
  return (
    v.prompt_tokens != null ||
    v.completion_tokens != null ||
    v.total_tokens != null ||
    v.reasoning_tokens != null ||
    v.prompt_cached_tokens != null ||
    v.cost_yuan != null
  );
}

const TokenBubble: React.FC<TokenBubbleProps> = ({ usage, messageId }) => {
  const [fetched, setFetched] = useState<CallItem | null>(null);
  const fetchedForRef = React.useRef<string>("");
  const inlineUsage = hasUsageFields(usage) ? usage : undefined;

  useEffect(() => {
    if (inlineUsage || !messageId || fetchedForRef.current === messageId) return;
    fetchedForRef.current = messageId;
    setFetched(null);
    (async () => {
      try {
        const res = await fetch(
          `/api/metrics/llm/calls?message_id=${encodeURIComponent(messageId)}&limit=1`,
        );
        if (!res.ok) return;
        const data: { items?: CallItem[] } = await res.json();
        if (data.items?.length) setFetched(data.items[0]);
      } catch {
        // silent
      }
    })();
  }, [inlineUsage, messageId]);

  const resolved = inlineUsage ?? fetched;
  if (!resolved) return null;

  const prompt = num(resolved.prompt_tokens);
  const completion = num(resolved.completion_tokens);
  const total = num(resolved.total_tokens) ?? (prompt ?? 0) + (completion ?? 0);
  const reasoning = num(resolved.reasoning_tokens);
  const cached = num(resolved.prompt_cached_tokens);
  const cacheHit = num(resolved.prompt_cache_hit);
  const cacheMiss = num(resolved.prompt_cache_miss);
  const cost =
    resolved.cost_yuan != null ? Number(resolved.cost_yuan) : undefined;

  if (total === 0 && prompt === undefined && completion === undefined)
    return null;

  return (
    <div className="token-bubble">
      {/* compact label */}
      <span className="token-bubble-label">token: {fmt(total)}</span>

      {/* expanded detail on hover */}
      <div className="token-bubble-detail">
        <table>
          <tbody>
            <tr>
              <td>prompt</td>
              <td>{fmt(prompt)}</td>
            </tr>
            <tr>
              <td>completion</td>
              <td>{fmt(completion)}</td>
            </tr>
            {reasoning !== undefined && (
              <tr>
                <td>reasoning</td>
                <td>{fmt(reasoning)}</td>
              </tr>
            )}
            {cached !== undefined && (
              <tr>
                <td>cached</td>
                <td>{fmt(cached)}</td>
              </tr>
            )}
            {cacheHit !== undefined && (
              <tr>
                <td>cache hit</td>
                <td>{fmt(cacheHit)}</td>
              </tr>
            )}
            {cacheMiss !== undefined && (
              <tr>
                <td>cache miss</td>
                <td>{fmt(cacheMiss)}</td>
              </tr>
            )}
            {cost !== undefined && (
              <tr className="token-bubble-cost-row">
                <td>cost</td>
                <td>¥{cost.toFixed(4)}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default TokenBubble;
