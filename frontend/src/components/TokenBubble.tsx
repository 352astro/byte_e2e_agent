import React, { useCallback, useEffect, useRef, useState } from "react";
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

function hasDetail(item: CallItem | null): boolean {
  return Boolean(
    item &&
      (item.prompt_tokens != null ||
        item.completion_tokens != null ||
        item.reasoning_tokens != null ||
        item.prompt_cached_tokens != null ||
        item.prompt_cache_hit != null ||
        item.prompt_cache_miss != null ||
        item.cost_yuan != null),
  );
}

const TokenBubble: React.FC<TokenBubbleProps> = ({ usage, messageId }) => {
  const [fetched, setFetched] = useState<CallItem | null>(null);
  const fetchedForRef = useRef<string>("");
  const fetchingRef = useRef(false);
  const lastFetchAtRef = useRef(0);

  // compact total from SSE (instant)
  const sseTotal = num(usage?.total_tokens);

  const fetchDetail = useCallback(
    async (force = false) => {
      if (!messageId || fetchingRef.current) return;
      const now = Date.now();
      if (!force && now - lastFetchAtRef.current < 600) return;
      if (!force && fetchedForRef.current === messageId && hasDetail(fetched)) {
        return;
      }
      fetchingRef.current = true;
      lastFetchAtRef.current = now;
      try {
        const res = await fetch(
          `/api/metrics/llm/calls?message_id=${encodeURIComponent(messageId)}&limit=1`,
        );
        if (!res.ok) return;
        const data: { items?: CallItem[] } = await res.json();
        if (data.items?.length) {
          setFetched(data.items[0]);
          fetchedForRef.current = messageId;
        }
      } catch {
        // silent
      } finally {
        fetchingRef.current = false;
      }
    },
    [fetched, messageId],
  );

  useEffect(() => {
    if (!messageId) return;
    fetchedForRef.current = "";
    setFetched(null);
    void fetchDetail(true);
  }, [messageId]);

  // compact label: SSE total > API total
  const compactTotal = sseTotal ?? num(fetched?.total_tokens);
  if (compactTotal === undefined && !fetched) return null;

  // hover detail always from API
  const detail = fetched;
  if (!detail && compactTotal === undefined) return null;

  return (
    <div
      className="token-bubble"
      onMouseEnter={() => {
        if (!hasDetail(fetched)) void fetchDetail();
      }}
    >
      {/* compact label */}
      <span className="token-bubble-label">token: {fmt(compactTotal)}</span>

      {/* expanded detail on hover */}
      <div className="token-bubble-detail">
        <table>
          <tbody>
            <tr>
              <td>prompt</td>
              <td>{fmt(num(detail?.prompt_tokens))}</td>
            </tr>
            <tr>
              <td>completion</td>
              <td>{fmt(num(detail?.completion_tokens))}</td>
            </tr>
            {detail?.reasoning_tokens != null && (
              <tr>
                <td>reasoning</td>
                <td>{fmt(num(detail.reasoning_tokens))}</td>
              </tr>
            )}
            {detail?.prompt_cached_tokens != null && (
              <tr>
                <td>cached</td>
                <td>{fmt(num(detail.prompt_cached_tokens))}</td>
              </tr>
            )}
            {detail?.prompt_cache_hit != null && (
              <tr>
                <td>cache hit</td>
                <td>{fmt(num(detail.prompt_cache_hit))}</td>
              </tr>
            )}
            {detail?.prompt_cache_miss != null && (
              <tr>
                <td>cache miss</td>
                <td>{fmt(num(detail.prompt_cache_miss))}</td>
              </tr>
            )}
            {detail?.cost_yuan != null && (
              <tr className="token-bubble-cost-row">
                <td>cost</td>
                <td>¥{detail.cost_yuan.toFixed(4)}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default TokenBubble;
