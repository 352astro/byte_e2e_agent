import { useRef } from "react";
import useAgentStream from "../hooks/useAgentStream";
import StepCard from "./StepCard";
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

  const composingRef = useRef(false);

  const onKeyDown = (e) => {
    if (e.key === "Enter") {
      if (e.ctrlKey || e.metaKey || e.shiftKey) {
        return;
      }
      if (composingRef.current) {
        return;
      }
      e.preventDefault();
      handleRun();
    }
  };

  const MAX_ROWS = 10;

  const handleChange = (e) => {
    setQuestion(e.target.value);
    const lines = e.target.value.split("\n").length;
    e.target.rows = Math.min(Math.max(lines, 1), MAX_ROWS);
  };

  return (
    <div className="agent-demo">
      {/* ── scrollable content ──────────────────── */}
      <div className="agent-scroll">
        <div className="agent-scroll-inner">
          {steps.map((step, i) => (
            <StepCard
              key={step.step}
              step={step}
              isLatest={i === steps.length - 1}
              index={i}
              onToggle={toggleStep}
              onExpandResult={expandResult}
            />
          ))}

          {answer !== null && (
            <div className="agent-answer">
              <h3>{"\u2705"} Answer</h3>
              <p>{answer}</p>
            </div>
          )}

          <div className="agent-bottom-spacer" />
        </div>
      </div>

      {/* ── fixed input bar ─────────────────────── */}
      <div className="agent-input-bar">
        <textarea
          className="agent-textarea"
          placeholder="Ask the agent something… (Enter to send, Ctrl/Shift+Enter for newline)"
          value={question}
          onChange={handleChange}
          onKeyDown={onKeyDown}
          onCompositionStart={() => {
            composingRef.current = true;
          }}
          onCompositionEnd={() => {
            composingRef.current = false;
          }}
          disabled={running}
          rows={1}
        />
        <button
          className="agent-send-btn"
          onClick={handleRun}
          disabled={running || !question.trim()}
        >
          {running ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
