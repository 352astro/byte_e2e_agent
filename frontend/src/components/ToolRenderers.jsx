import { RESULT_PREVIEW_LINES } from "../hooks/useAgentStream";

export default function renderToolEvent(ev, evIdx, stepIdx, expandResult) {
  // ── Shell: terminal output ────────────────────
  if (ev.type === "terminal_stream") {
    return (
      <div key={evIdx} className="event terminal-output">
        <pre>{ev.output}</pre>
      </div>
    );
  }

  // ── tool_stream (in-progress) ──────────────────
  if (ev.type === "tool_stream") {
    const name = ev.name || "…";
    return (
      <div key={evIdx} className="event tool-stream">
        <span className="label">{"\u23F3"} {name}</span>
        <span className="tool-stream-progress">
          …writing {ev.argsLen} tokens
        </span>
      </div>
    );
  }

  // ── tool_call ──────────────────────────────────
  if (ev.type === "tool_call") {
    // Shell: render command as styled bash block with timeout badge
    if (ev.tool === "Shell") {
      const cmd = ev.params?.command || "";
      const timeout = ev.params?.timeout_ms
        ? `${Math.round(ev.params.timeout_ms / 1000)}s`
        : null;
      return (
        <div key={evIdx} className="event shell-call">
          <span className="label">{"\uD83D\uDD27"} Shell</span>
          {timeout && <span className="shell-timeout-badge">{timeout}</span>}
          <pre className="shell-command">{cmd}</pre>
        </div>
      );
    }

    // Fallback: render params as formatted JSON
    return (
      <div key={evIdx} className="event tool-call">
        <span className="label">
          {"\uD83D\uDD27"} {ev.tool}
        </span>
        {ev.params && Object.keys(ev.params).length > 0 && (
          <pre className="params">{JSON.stringify(ev.params, null, 2)}</pre>
        )}
      </div>
    );
  }

  // ── tool_result ────────────────────────────────
  if (ev.type === "tool_result") {
    const lines = (ev.result || "").split("\n");
    const truncated = lines.length > RESULT_PREVIEW_LINES && !ev.expanded;
    const display = truncated
      ? lines.slice(0, RESULT_PREVIEW_LINES).join("\n")
      : ev.result;
    return (
      <div key={evIdx} className="event tool-result">
        <pre>{display}</pre>
        {truncated && (
          <button
            className="expand-btn"
            onClick={() => expandResult(stepIdx, evIdx)}
          >
            Show all ({lines.length} lines)
          </button>
        )}
      </div>
    );
  }

  // ── error ──────────────────────────────────────
  if (ev.type === "error") {
    return (
      <div key={evIdx} className="event error">
        {"\u26A0\uFE0F"} {ev.message}
      </div>
    );
  }

  // ── plan / subtask — compact summary ───────────
  if (ev.type === "plan_rewrite") {
    const items = ev.items || [];
    return (
      <div
        key={evIdx}
        className="event"
        style={{ color: "#9333ea", fontSize: "0.83rem" }}
      >
        {"\uD83D\uDCCB"} Plan: {items.length} item(s)
      </div>
    );
  }
  if (ev.type === "plan_advance") {
    return (
      <div
        key={evIdx}
        className="event"
        style={{ color: "#9333ea", fontSize: "0.83rem" }}
      >
        {"\uD83D\uDCCB"} Plan: {ev.summary || ev.state}
      </div>
    );
  }
  if (ev.type === "subtask_start") {
    return (
      <div
        key={evIdx}
        className="event"
        style={{ color: "#0891b2", fontSize: "0.83rem" }}
      >
        {"\uD83E\uDD16"} Sub-agent: {ev.prompt?.slice(0, 80)}…
      </div>
    );
  }
  if (ev.type === "subtask_end") {
    const r = ev.result || "";
    return (
      <div
        key={evIdx}
        className="event"
        style={{ color: "#0891b2", fontSize: "0.83rem" }}
      >
        {"\uD83E\uDD16"} Sub-agent done: {r.slice(0, 100)}
      </div>
    );
  }

  return null;
}
