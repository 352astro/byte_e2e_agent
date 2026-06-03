import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import type { CSSProperties, PointerEvent } from "react";
import Icon from "./Icon";
import type { components } from "../types.generated";

type ModelPricingItem = components["schemas"]["ModelPricingItem"] & {
  cached_input_price_per_1m?: number | null;
};
type Span = "week" | "month" | "year";
type Scope = "current" | "global";

interface MetricsPanelProps {
  onClose: () => void;
}

interface SeriesBucket {
  bucket: string;
  model: string;
  calls: number;
  input_tokens: number;
  cached_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
  cost_yuan: number;
}

interface SeriesResponse {
  span: Span;
  unit: "day" | "month";
  models: string[];
  buckets: SeriesBucket[];
}

const spanLabels: Record<Span, string> = {
  week: "Week",
  month: "Month",
  year: "Year",
};

const tokenColors = {
  cacheHit: "#38bdf8",
  cacheMiss: "#2563eb",
  reasoning: "#f59e0b",
  completion: "#16a34a",
};

function fmtMoney(v: number): string {
  if (v >= 1000) return `¥${v.toFixed(0)}`;
  if (v >= 10) return `¥${v.toFixed(2)}`;
  return `¥${v.toFixed(4)}`;
}

function fmtTokens(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}k`;
  return String(v);
}

function emptyBucket(bucket: string): SeriesBucket {
  return {
    bucket,
    model: "all",
    calls: 0,
    input_tokens: 0,
    cached_tokens: 0,
    output_tokens: 0,
    reasoning_tokens: 0,
    total_tokens: 0,
    cost_yuan: 0,
  };
}

function formatUtcDay(date: Date): string {
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatUtcMonth(date: Date): string {
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  return `${year}-${month}`;
}

function expectedBuckets(span: Span): string[] {
  const now = new Date();
  const year = now.getUTCFullYear();
  const month = now.getUTCMonth();
  if (span === "year") {
    return Array.from({ length: 12 }, (_, i) => {
      const d = new Date(Date.UTC(year, i, 1));
      return formatUtcMonth(d);
    });
  }

  if (span === "month") {
    const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
    return Array.from({ length: daysInMonth }, (_, i) => {
      const d = new Date(Date.UTC(year, month, i + 1));
      return formatUtcDay(d);
    });
  }

  const currentDay = new Date(Date.UTC(year, month, now.getUTCDate()));
  const weekDay = currentDay.getUTCDay();
  const mondayOffset = weekDay === 0 ? 6 : weekDay - 1;
  const monday = new Date(currentDay);
  monday.setUTCDate(currentDay.getUTCDate() - mondayOffset);
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(monday);
    d.setUTCDate(monday.getUTCDate() + i);
    return formatUtcDay(d);
  });
}

function aggregateBuckets(buckets: SeriesBucket[]): SeriesBucket[] {
  const map = new Map<string, SeriesBucket>();
  for (const b of buckets) {
    const item =
      map.get(b.bucket) ||
      ({
        bucket: b.bucket,
        model: "all",
        calls: 0,
        input_tokens: 0,
        cached_tokens: 0,
        output_tokens: 0,
        reasoning_tokens: 0,
        total_tokens: 0,
        cost_yuan: 0,
      } satisfies SeriesBucket);
    item.calls += b.calls || 0;
    item.input_tokens += b.input_tokens || 0;
    item.cached_tokens += b.cached_tokens || 0;
    item.output_tokens += b.output_tokens || 0;
    item.reasoning_tokens += b.reasoning_tokens || 0;
    item.total_tokens += b.total_tokens || 0;
    item.cost_yuan += b.cost_yuan || 0;
    map.set(b.bucket, item);
  }
  return Array.from(map.values()).sort((a, b) => a.bucket.localeCompare(b.bucket));
}

function fillBuckets(buckets: SeriesBucket[], span: Span): SeriesBucket[] {
  const aggregated = aggregateBuckets(buckets);
  const map = new Map(aggregated.map((bucket) => [bucket.bucket, bucket]));
  return expectedBuckets(span).map((bucket) => map.get(bucket) || emptyBucket(bucket));
}

function shouldShowXAxisLabel(index: number, total: number): boolean {
  if (total <= 12) return true;
  const step = Math.ceil(total / 8);
  return index === 0 || index === total - 1 || index % step === 0;
}

function smoothPath(points: { x: number; y: number }[]): string {
  if (points.length === 0) return "";
  if (points.length === 1) return `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`;
  const slopes = points.slice(0, -1).map((p, i) => {
    const next = points[i + 1];
    return (next.y - p.y) / Math.max(next.x - p.x, 1);
  });
  const tangents = points.map((_, i) => {
    if (i === 0) return slopes[0];
    if (i === points.length - 1) return slopes[slopes.length - 1];
    const prev = slopes[i - 1];
    const next = slopes[i];
    if (prev === 0 || next === 0 || Math.sign(prev) !== Math.sign(next)) return 0;
    return (prev + next) / 2;
  });
  const commands = [`M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`];
  for (let i = 0; i < points.length - 1; i += 1) {
    const p1 = points[i];
    const p2 = points[i + 1];
    const dx = p2.x - p1.x;
    const minY = Math.min(p1.y, p2.y);
    const maxY = Math.max(p1.y, p2.y);
    const c1x = p1.x + dx / 3;
    const c1y = Math.min(Math.max(p1.y + (tangents[i] * dx) / 3, minY), maxY);
    const c2x = p2.x - dx / 3;
    const c2y = Math.min(
      Math.max(p2.y - (tangents[i + 1] * dx) / 3, minY),
      maxY,
    );
    commands.push(
      `C ${c1x.toFixed(1)} ${c1y.toFixed(1)} ${c2x.toFixed(1)} ${c2y.toFixed(1)} ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`,
    );
  }
  return commands.join(" ");
}

function CostChart({ rows }: { rows: SeriesBucket[] }) {
  const width = 720;
  const height = 210;
  const pad = { left: 50, right: 18, top: 18, bottom: 34 };
  const values = rows.map((r) => r.cost_yuan || 0);
  const max = Math.max(...values, 0.0001);
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const points = rows.map((r, i) => {
    const x =
      pad.left + (rows.length <= 1 ? 0 : (i / (rows.length - 1)) * innerW);
    const y = pad.top + innerH - ((r.cost_yuan || 0) / max) * innerH;
    return { x, y, row: r };
  });
  const d = smoothPath(points);

  return (
    <svg className="metrics-chart-svg" viewBox={`0 0 ${width} ${height}`}>
      {[0, 0.25, 0.5, 0.75, 1].map((t) => {
        const y = pad.top + innerH - t * innerH;
        return (
          <g key={t}>
            <line x1={pad.left} x2={width - pad.right} y1={y} y2={y} />
            <text x={pad.left - 8} y={y + 4} textAnchor="end">
              {fmtMoney(max * t)}
            </text>
          </g>
        );
      })}
      <path d={d} className="metrics-cost-line" />
      {points.map((p, index) => {
        const hasData = (p.row.cost_yuan || 0) > 0;
        const left =
          points.length <= 1
            ? pad.left
            : p.x - (p.x - (points[index - 1]?.x ?? pad.left)) / 2;
        const right =
          points.length <= 1
            ? width - pad.right
            : p.x + (((points[index + 1]?.x ?? width - pad.right) - p.x) / 2);
        const tooltipX = Math.min(p.x + 8, width - 134);
        const tooltipY = Math.max(8, p.y - 48);
        return (
          <g
            key={p.row.bucket}
            className={`metrics-cost-point${hasData ? " has-data" : ""}`}
          >
            {hasData ? (
              <rect
                className="metrics-cost-hover-target"
                x={left}
                y={pad.top}
                width={Math.max(1, right - left)}
                height={innerH}
              />
            ) : null}
            <circle cx={p.x} cy={p.y} r={3.5} />
            {hasData ? (
              <foreignObject
                className="metrics-svg-tooltip"
                x={tooltipX}
                y={tooltipY}
                width={126}
                height={44}
              >
                <div className="metrics-tooltip-box">
                  <strong>{p.row.bucket}</strong>
                  <span>{fmtMoney(p.row.cost_yuan)}</span>
                </div>
              </foreignObject>
            ) : null}
          </g>
        );
      })}
      {points.map((p, i) =>
        shouldShowXAxisLabel(i, points.length) ? (
          <text key={p.row.bucket} x={p.x} y={height - 10} textAnchor="middle">
            {p.row.bucket}
          </text>
        ) : null,
      )}
    </svg>
  );
}

function TokenBars({ rows }: { rows: SeriesBucket[] }) {
  const width = 720;
  const height = 260;
  const pad = { left: 54, right: 18, top: 18, bottom: 42 };
  const max = Math.max(...rows.map((r) => r.total_tokens || 0), 1);
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const gap = rows.length > 18 ? 3 : 8;
  const barW = Math.max(6, (innerW - gap * Math.max(rows.length - 1, 0)) / rows.length);

  return (
    <svg className="metrics-token-chart" viewBox={`0 0 ${width} ${height}`}>
      {[0, 0.25, 0.5, 0.75, 1].map((t) => {
        const y = pad.top + innerH - t * innerH;
        return (
          <g key={t}>
            <line x1={pad.left} x2={width - pad.right} y1={y} y2={y} />
            <text x={pad.left - 8} y={y + 4} textAnchor="end">
              {fmtTokens(max * t)}
            </text>
          </g>
        );
      })}
      {rows.map((r, index) => {
        const segments = [
          ["cache hit", r.cached_tokens, tokenColors.cacheHit],
          ["cache miss", r.input_tokens, tokenColors.cacheMiss],
          ["reasoning", r.reasoning_tokens, tokenColors.reasoning],
          ["completion", r.output_tokens, tokenColors.completion],
        ] as const;
        const tooltip = [
          `${r.bucket}`,
          `Total: ${fmtTokens(r.total_tokens)}`,
          `Cache hit: ${fmtTokens(r.cached_tokens)}`,
          `Cache miss: ${fmtTokens(r.input_tokens)}`,
          `Reasoning: ${fmtTokens(r.reasoning_tokens)}`,
          `Completion: ${fmtTokens(r.output_tokens)}`,
        ].join("\n");
        const x = pad.left + index * (barW + gap);
        let y = pad.top + innerH;
        const hasData = (r.total_tokens || 0) > 0;
        const tooltipX = Math.min(x + barW + 8, width - 178);
        const tooltipY = pad.top + 12;
        return (
          <g
            key={r.bucket}
            className={`metrics-token-bar${hasData ? " has-data" : ""}`}
          >
            {hasData ? (
              <rect
                className="metrics-token-hover-target"
                x={x - gap / 2}
                y={pad.top}
                width={barW + gap}
                height={innerH}
              />
            ) : null}
            {segments.map(([name, value, color]) => {
              if (value <= 0) return null;
              const h = Math.max(1, (value / max) * innerH);
              y -= h;
              return (
                <rect
                  key={name}
                  x={x}
                  y={y}
                  width={barW}
                  height={h}
                  fill={color}
                />
              );
            })}
            {shouldShowXAxisLabel(index, rows.length) ? (
              <text
                x={x + barW / 2}
                y={height - 12}
                textAnchor="middle"
                className="metrics-token-x-label"
              >
                {r.bucket}
              </text>
            ) : null}
            {hasData ? (
              <foreignObject
                className="metrics-svg-tooltip metrics-token-tooltip"
                x={tooltipX}
                y={tooltipY}
                width={170}
                height={106}
              >
                <div className="metrics-tooltip-box">
                  {tooltip.split("\n").map((line, lineIndex) =>
                    lineIndex === 0 ? (
                      <strong key={line}>{line}</strong>
                    ) : (
                      <span key={line}>{line}</span>
                    ),
                  )}
                </div>
              </foreignObject>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}

export default function MetricsPanel({ onClose }: MetricsPanelProps) {
  const [position, setPosition] = useState({ x: 260, y: 64 });
  const windowRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
  } | null>(null);

  const [workspace, setWorkspace] = useState("");
  const [scope, setScope] = useState<Scope>("current");
  const [costSpan, setCostSpan] = useState<Span>("week");
  const [tokenSpan, setTokenSpan] = useState<Span>("week");
  const [selectedModel, setSelectedModel] = useState("all");
  const [costSeries, setCostSeries] = useState<SeriesResponse | null>(null);
  const [tokenSeries, setTokenSeries] = useState<SeriesResponse | null>(null);
  const [pricing, setPricing] = useState<ModelPricingItem[]>([]);
  const [configOpen, setConfigOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [newModelId, setNewModelId] = useState("");
  const [newCacheHitPrice, setNewCacheHitPrice] = useState("");
  const [newCacheMissPrice, setNewCacheMissPrice] = useState("");
  const [newReasoningPrice, setNewReasoningPrice] = useState("");
  const [newCompletionPrice, setNewCompletionPrice] = useState("");

  useEffect(() => {
    fetch("/api/workspace")
      .then((r) => r.json())
      .then((data: { workspace: string }) => setWorkspace(data.workspace || ""))
      .catch(() => {});
  }, []);

  const queryScope = useCallback(
    (span: Span, model?: string) => {
      const params = new URLSearchParams({ span });
      if (scope === "current" && workspace) {
        params.set("workspace_root", workspace);
      }
      if (model && model !== "all") {
        params.set("model", model);
      }
      return params.toString();
    },
    [scope, workspace],
  );

  const fetchPricing = useCallback(async () => {
    const res = await fetch("/api/metrics/llm/pricing");
    if (!res.ok) throw new Error(`Pricing returned ${res.status}`);
    const data = await res.json();
    setPricing(Array.isArray(data) ? data : []);
  }, []);

  const fetchSeries = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [costRes, tokenRes] = await Promise.all([
        fetch(`/api/metrics/llm/series?${queryScope(costSpan)}`),
        fetch(`/api/metrics/llm/series?${queryScope(tokenSpan, selectedModel)}`),
        fetchPricing(),
      ]);
      if (!costRes.ok) throw new Error(`Cost series returned ${costRes.status}`);
      if (!tokenRes.ok) throw new Error(`Token series returned ${tokenRes.status}`);
      setCostSeries(await costRes.json());
      setTokenSeries(await tokenRes.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [costSpan, tokenSpan, selectedModel, queryScope, fetchPricing]);

  useEffect(() => {
    void fetchSeries();
  }, [fetchSeries]);

  const models = useMemo(() => {
    const set = new Set<string>();
    for (const m of costSeries?.models || []) set.add(m);
    for (const m of tokenSeries?.models || []) set.add(m);
    for (const p of pricing) set.add(p.model_id);
    return Array.from(set).sort();
  }, [costSeries, tokenSeries, pricing]);

  const costRows = useMemo(
    () => fillBuckets(costSeries?.buckets || [], costSeries?.span || costSpan),
    [costSeries, costSpan],
  );
  const tokenRows = useMemo(
    () => fillBuckets(tokenSeries?.buckets || [], tokenSeries?.span || tokenSpan),
    [tokenSeries, tokenSpan],
  );

  const upsertPricing = async (
    modelId: string,
    inputPrice: number,
    outputPrice: number,
    reasoningPrice?: number | null,
    cachedInputPrice?: number | null,
  ) => {
    const res = await fetch("/api/metrics/llm/pricing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model_id: modelId,
        input_price: inputPrice,
        output_price: outputPrice,
        reasoning_price: reasoningPrice ?? null,
        cached_input_price: cachedInputPrice ?? null,
      }),
    });
    if (!res.ok) throw new Error(`Save returned ${res.status}`);
    await fetchSeries();
  };

  const addPricing = async () => {
    if (!newModelId.trim()) return;
    try {
      await upsertPricing(
        newModelId.trim(),
        parseFloat(newCacheMissPrice) || 0,
        parseFloat(newCompletionPrice) || 0,
        newReasoningPrice ? parseFloat(newReasoningPrice) : null,
        newCacheHitPrice ? parseFloat(newCacheHitPrice) : null,
      );
      setNewModelId("");
      setNewCacheHitPrice("");
      setNewCacheMissPrice("");
      setNewReasoningPrice("");
      setNewCompletionPrice("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const startDrag = (e: PointerEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest("button, select, input")) return;
    dragRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      originX: position.x,
      originY: position.y,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const moveDrag = (e: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    const rect = windowRef.current?.getBoundingClientRect();
    const width = rect?.width || 820;
    const height = rect?.height || 620;
    const maxX = Math.max(16, window.innerWidth - width - 16);
    const maxY = Math.max(16, window.innerHeight - height - 16);
    setPosition({
      x: Math.min(Math.max(16, drag.originX + e.clientX - drag.startX), maxX),
      y: Math.min(Math.max(16, drag.originY + e.clientY - drag.startY), maxY),
    });
  };

  const stopDrag = (e: PointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId === e.pointerId) dragRef.current = null;
  };

  return (
    <div
      ref={windowRef}
      className="settings-window metrics-window"
      style={{ left: position.x, top: position.y }}
    >
      <div
        className="settings-titlebar"
        onPointerDown={startDrag}
        onPointerMove={moveDrag}
        onPointerUp={stopDrag}
        onPointerCancel={stopDrag}
      >
        <div className="settings-title">Metrics</div>
        <button className="settings-close-btn" type="button" onClick={onClose}>
          x
        </button>
      </div>

      <main className="metrics-dashboard">
        <div className="metrics-toolbar">
          <div className="metrics-field">
            <span>Workspace</span>
            <select
              className="metrics-select"
              value={scope}
              onChange={(e) => setScope(e.target.value as Scope)}
            >
              <option value="current">Current</option>
              <option value="global">Global</option>
            </select>
          </div>
          <div className="metrics-workspace-path" title={workspace}>
            {scope === "global" ? "All workspaces" : workspace || "Current workspace"}
          </div>
          <button
            className="settings-refresh-btn metrics-config-btn"
            type="button"
            onClick={() => setConfigOpen(true)}
          >
            <Icon name="settings" size={14} />
            Config
          </button>
        </div>

        {error && <div className="memory-error">{error}</div>}

        <section className="metrics-card">
          <div className="metrics-card-head">
            <div>
              <h2>Cost Trend</h2>
              <span>
                X-axis: {costSeries?.unit === "month" ? "months" : "days"} /
                Y-axis: CNY
              </span>
            </div>
            <div className="metrics-segment">
              {(Object.keys(spanLabels) as Span[]).map((span) => (
                <button
                  key={span}
                  type="button"
                  className={costSpan === span ? "active" : ""}
                  onClick={() => setCostSpan(span)}
                >
                  {spanLabels[span]}
                </button>
              ))}
            </div>
          </div>
          {loading && !costSeries ? (
            <div className="metrics-empty">Loading...</div>
          ) : costRows.length > 0 ? (
            <CostChart rows={costRows} />
          ) : (
            <div className="metrics-empty">No cost data.</div>
          )}
        </section>

        <section className="metrics-card metrics-card--fill">
          <div className="metrics-card-head">
            <div>
              <h2>Token Usage</h2>
              <span>
                X-axis: {tokenSeries?.unit === "month" ? "months" : "days"} /
                Y-axis: tokens
              </span>
            </div>
            <div className="metrics-card-controls">
              <div className="metrics-segment">
                {(Object.keys(spanLabels) as Span[]).map((span) => (
                  <button
                    key={span}
                    type="button"
                    className={tokenSpan === span ? "active" : ""}
                    onClick={() => setTokenSpan(span)}
                  >
                    {spanLabels[span]}
                  </button>
                ))}
              </div>
              <select
                className="metrics-select"
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
              >
                <option value="all">All models</option>
                {models.map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="metrics-token-legend">
            <span style={{ "--c": tokenColors.cacheHit } as CSSProperties}>
              cache hit
            </span>
            <span style={{ "--c": tokenColors.cacheMiss } as CSSProperties}>
              cache miss
            </span>
            <span style={{ "--c": tokenColors.reasoning } as CSSProperties}>
              reasoning
            </span>
            <span style={{ "--c": tokenColors.completion } as CSSProperties}>
              completion
            </span>
          </div>
          {tokenRows.length > 0 ? (
            <TokenBars rows={tokenRows} />
          ) : (
            <div className="metrics-empty">No token data.</div>
          )}
        </section>
      </main>

      {configOpen && (
        <div className="metrics-config-popover">
          <div className="metrics-config-head">
            <div>
              <h2>Pricing Config</h2>
              <span>Auto-discovered model IDs can be edited here.</span>
            </div>
            <div className="metrics-pricing-unit">Unit: ¥ / 1M tokens</div>
            <button
              className="settings-close-btn"
              type="button"
              onClick={() => setConfigOpen(false)}
            >
              x
            </button>
          </div>
          <div className="metrics-pricing-header">
            <span>model-id</span>
            <span>cache hit</span>
            <span>cache miss</span>
            <span>reasoning</span>
            <span>completion</span>
            <span />
          </div>
          <div className="metrics-pricing-list">
            {pricing.map((p) => (
              <PricingRow key={p.model_id} item={p} onSave={upsertPricing} />
            ))}
          </div>
          <div className="metrics-pricing-add">
            <input
              className="metrics-input"
              placeholder="model-id"
              value={newModelId}
              onChange={(e) => setNewModelId(e.target.value)}
            />
            <input
              className="metrics-input"
              placeholder="cache hit"
              type="number"
              value={newCacheHitPrice}
              onChange={(e) => setNewCacheHitPrice(e.target.value)}
            />
            <input
              className="metrics-input"
              placeholder="cache miss"
              type="number"
              value={newCacheMissPrice}
              onChange={(e) => setNewCacheMissPrice(e.target.value)}
            />
            <input
              className="metrics-input"
              placeholder="reasoning"
              type="number"
              value={newReasoningPrice}
              onChange={(e) => setNewReasoningPrice(e.target.value)}
            />
            <input
              className="metrics-input"
              placeholder="completion"
              type="number"
              value={newCompletionPrice}
              onChange={(e) => setNewCompletionPrice(e.target.value)}
            />
            <button
              className="settings-refresh-btn"
              type="button"
              onClick={() => void addPricing()}
              disabled={!newModelId.trim()}
            >
              Add model-id
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function PricingRow({
  item,
  onSave,
}: {
  item: ModelPricingItem;
  onSave: (
    modelId: string,
    inputPrice: number,
    outputPrice: number,
    reasoningPrice?: number | null,
    cachedInputPrice?: number | null,
  ) => Promise<void>;
}) {
  const [cacheHit, setCacheHit] = useState(
    item.cached_input_price_per_1m == null
      ? ""
      : String(item.cached_input_price_per_1m),
  );
  const [cacheMiss, setCacheMiss] = useState(String(item.input_price_per_1m));
  const [reasoning, setReasoning] = useState(
    item.reasoning_price_per_1m == null ? "" : String(item.reasoning_price_per_1m),
  );
  const [completion, setCompletion] = useState(String(item.output_price_per_1m));
  return (
    <div className="metrics-pricing-row">
      <div className="metrics-pricing-model" title={item.model_id}>
        <span>{item.model_id}</span>
        <small>{item.is_custom ? "custom" : "auto"}</small>
      </div>
      <input
        className="metrics-input"
        aria-label="cache hit price"
        placeholder="cache hit"
        value={cacheHit}
        onChange={(e) => setCacheHit(e.target.value)}
      />
      <input
        className="metrics-input"
        aria-label="cache miss price"
        placeholder="cache miss"
        value={cacheMiss}
        onChange={(e) => setCacheMiss(e.target.value)}
      />
      <input
        className="metrics-input"
        aria-label="reasoning price"
        placeholder="reasoning"
        value={reasoning}
        onChange={(e) => setReasoning(e.target.value)}
      />
      <input
        className="metrics-input"
        aria-label="completion price"
        placeholder="completion"
        value={completion}
        onChange={(e) => setCompletion(e.target.value)}
      />
      <button
        className="settings-refresh-btn"
        type="button"
        onClick={() =>
          void onSave(
            item.model_id,
            parseFloat(cacheMiss) || 0,
            parseFloat(completion) || 0,
            reasoning ? parseFloat(reasoning) : null,
            cacheHit ? parseFloat(cacheHit) : null,
          )
        }
      >
        Save
      </button>
    </div>
  );
}
