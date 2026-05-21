import useAgentStream, { RESULT_PREVIEW_LINES } from "../hooks/useAgentStream";
import "./AgentDemo.css";

export default function AgentDemo() {
  const {
    question,
    setQuestion,
    running,
    steps,
    answer,
    handleRun,
    toggleStep,
    expandResult,
  } = useAgentStream();

  return (
    <div className="agent-demo">
      <h2>Agent Demo</h2>

      {/* ── input ──────────────────────────────── */}
      <div className="agent-input">
        <input
          type="text"
          placeholder="Ask the agent something..."
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleRun()}
          disabled={running}
        />
        <button onClick={handleRun} disabled={running || !question.trim()}>
          {running ? "Thinking..." : "Run"}
        </button>
      </div>

      {/* ── step cards ──────────────────────────── */}
      {steps.map((step, i) => (
        <div key={step.step} className="step-card">
          <div className="step-header" onClick={() => toggleStep(i)}>
            <span className="step-num">Step {step.step}</span>
            <span className="step-toggle">{step.open ? "\u25BE" : "\u25B8"}</span>
          </div>

          {step.open && (
            <div className="step-body">
              {/* Deep Think */}
              {step.reasoning && (
                <details className="reasoning-block">
                  <summary className="reasoning-summary">
                    {"\uD83D\uDC9C"} Deep Think ({step.reasoning.length} chars)
                  </summary>
                  <pre className="reasoning-text">{step.reasoning}</pre>
                </details>
              )}

              {/* Thought */}
              {step.thought && (
                <details className="thought-block" open>
                  <summary className="thought-summary">
                    {"\uD83D\uDCAD"} Thought ({step.thought.length} chars)
                  </summary>
                  <pre className="thought-text">{step.thought}</pre>
                </details>
              )}

              {/* Tool events */}
              {step.events.map((ev, evIdx) => {
                if (ev.type === "tool_call") {
                  return (
                    <div key={evIdx} className="event tool-call">
                      <span className="label">{"\uD83D\uDD27"} {ev.tool}</span>
                      {ev.params && Object.keys(ev.params).length > 0 && (
                        <pre className="params">
                          {JSON.stringify(ev.params, null, 2)}
                        </pre>
                      )}
                    </div>
                  );
                }
                if (ev.type === "tool_result") {
                  const lines = (ev.result || "").split("\n");
                  const truncated =
                    lines.length > RESULT_PREVIEW_LINES && !ev.expanded;
                  const display = truncated
                    ? lines.slice(0, RESULT_PREVIEW_LINES).join("\n")
                    : ev.result;
                  return (
                    <div key={evIdx} className="event tool-result">
                      <pre>{display}</pre>
                      {truncated && (
                        <button
                          className="expand-btn"
                          onClick={() => expandResult(i, evIdx)}
                        >
                          Show all ({lines.length} lines)
                        </button>
                      )}
                    </div>
                  );
                }
                if (ev.type === "terminal_stream") {
                  return (
                    <div key={evIdx} className="event terminal-output">
                      <pre>{ev.output}</pre>
                    </div>
                  );
                }
                if (ev.type === "error") {
                  return (
                    <div key={evIdx} className="event error">
                      {"\u26A0\uFE0F"} {ev.message}
                    </div>
                  );
                }
                return null;
              })}
            </div>
          )}
        </div>
      ))}

      {/* ── answer ──────────────────────────────── */}
      {answer !== null && (
        <div className="agent-answer">
          <h3>{"\u2705"} Answer</h3>
          <p>{answer}</p>
        </div>
      )}
    </div>
  );
}
