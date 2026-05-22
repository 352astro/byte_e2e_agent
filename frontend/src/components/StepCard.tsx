import Markdown from "./Markdown";
import renderToolEvent from "./ToolRenderers";
import type { Step } from "../types";

interface StepCardProps {
  step: Step;
  isLatest: boolean;
  onToggle: (stepId: number) => void;
  onExpandResult: (stepId: number, evIdx: number) => void;
}

export default function StepCard({
  step,
  isLatest,
  onToggle,
  onExpandResult,
}: StepCardProps) {
  return (
    <div className="step-card">
      <div className="step-header" onClick={() => onToggle(step.step)}>
        <span className="step-num">Step {step.step}</span>
        <span className="step-toggle">{step.open ? "\u25BE" : "\u25B8"}</span>
      </div>

      {step.open && (
        <div className="step-body">
          {step.reasoning && (
            <details className="reasoning-block" open={isLatest}>
              <summary className="reasoning-summary">
                {"\uD83D\uDC9C"} Thinking ({step.reasoning.length} chars)
              </summary>
              <Markdown text={step.reasoning} />
            </details>
          )}

          {step.action && (
            <div className="response-block">
              <span className="response-label">{"\uD83D\uDCAC"} Response</span>
              <Markdown text={step.action} />
            </div>
          )}

          {step.events.map((ev, evIdx) =>
            renderToolEvent(ev, evIdx, step.step, onExpandResult),
          )}
        </div>
      )}
    </div>
  );
}
