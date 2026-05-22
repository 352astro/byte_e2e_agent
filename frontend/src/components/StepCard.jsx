import renderToolEvent from "./ToolRenderers";

export default function StepCard({
  step,
  isLatest,
  index,
  onToggle,
  onExpandResult,
}) {
  return (
    <div className="step-card">
      <div className="step-header" onClick={() => onToggle(index)}>
        <span className="step-num">Step {step.step}</span>
        <span className="step-toggle">{step.open ? "\u25BE" : "\u25B8"}</span>
      </div>

      {step.open && (
        <div className="step-body">
          {/* Thinking (DeepSeek reasoning_content) */}
          {step.reasoning && (
            <details className="reasoning-block" open={isLatest}>
              <summary className="reasoning-summary">
                {"\uD83D\uDC9C"} Thinking ({step.reasoning.length} chars)
              </summary>
              <pre className="reasoning-text">{step.reasoning}</pre>
            </details>
          )}

          {/* Response (LLM text output) */}
          {step.action && (
            <div className="response-block">
              <span className="response-label">{"\uD83D\uDCAC"} Response</span>
              <pre className="response-text">{step.action}</pre>
            </div>
          )}

          {/* Tool events — delegated to specialized renderers */}
          {step.events.map((ev, evIdx) =>
            renderToolEvent(ev, evIdx, index, onExpandResult)
          )}
        </div>
      )}
    </div>
  );
}
