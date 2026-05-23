import { useState, useRef } from "react";
import useAgentStream from "../hooks/useAgentStream";
import Markdown from "./Markdown";
import StepCard from "./StepCard";
import type { Step, SessionCache } from "../types";
import "./AgentDemo.css";

interface AgentDemoProps {
  sessionId: string | null;
  pendingNew: boolean;
  workspace: string;
  onSessionCreated: (sid: string, workspace?: string) => void;
  cache: SessionCache;
}

interface ItemUser {
  type: "user_msg";
  key: string;
  content: string;
}

interface ItemStep {
  type: "step";
  key: string;
  step: Step;
  isLatest: boolean;
}

type Item = ItemUser | ItemStep;

export default function AgentDemo({
  sessionId,
  pendingNew,
  workspace,
  onSessionCreated,
  cache,
}: AgentDemoProps) {
  const {
    question,
    setQuestion,
    running,
    steps,
    answer,
    messages,
    handleRun,
    toggleStep,
    expandResult,
  } = useAgentStream({
    sessionId,
    pendingNew,
    workspace,
    onSessionCreated,
    cache,
  });

  const composingRef = useRef(false);
  const [rows, setRows] = useState(1);
  const MAX_ROWS = 10;

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter") {
      if (e.ctrlKey || e.metaKey || e.shiftKey) return;
      if (composingRef.current) return;
      e.preventDefault();
      handleRun();
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setQuestion(e.target.value);
    const lines = e.target.value.split("\n").length;
    setRows(Math.min(Math.max(lines, 1), MAX_ROWS));
  };

  // Interleave: user message → its response steps → next user message → ...
  const items: Item[] = [];
  const stepGroups: Record<number, Step[]> = {};
  for (const s of steps) {
    const mi = s.msgIndex ?? 0;
    if (!stepGroups[mi]) stepGroups[mi] = [];
    stepGroups[mi].push(s);
  }
  for (let mi = 0; mi < messages.length; mi++) {
    items.push({
      type: "user_msg",
      key: `msg-${mi}`,
      content: messages[mi].content,
    });
    const group = stepGroups[mi] || [];
    for (let si = 0; si < group.length; si++) {
      const s = group[si];
      items.push({
        type: "step",
        key: `step-${s.step}`,
        step: s,
        isLatest: s === steps[steps.length - 1],
      });
    }
  }
  // Steps without a matching message (e.g., still streaming for latest)
  const unmatched = steps.filter((s) => !messages[s.msgIndex ?? 0]);
  for (const s of unmatched) {
    items.push({
      type: "step",
      key: `step-${s.step}`,
      step: s,
      isLatest: s === steps[steps.length - 1],
    });
  }

  return (
    <div className="agent-demo">
      <div className="agent-scroll">
        <div className="agent-scroll-inner">
          {items.map((item) => {
            if (item.type === "user_msg") {
              return (
                <div key={item.key} className="user-bubble">
                  <span className="user-bubble-label">You</span>
                  <p>{item.content}</p>
                </div>
              );
            }
            const step = item.step;
            return (
              <StepCard
                key={item.key}
                step={step}
                isLatest={item.isLatest}
                onToggle={toggleStep}
                onExpandResult={expandResult}
              />
            );
          })}

          {answer != null && answer !== "" && (
            <div className="agent-answer">
              <h3>{"\u2705"} Answer</h3>
              <Markdown text={answer} />
            </div>
          )}

          <div className="agent-bottom-spacer" />
        </div>
      </div>

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
          rows={rows}
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
