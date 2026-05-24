import { useState, useRef } from "react";
import useAgentStream from "../hooks/useAgentStream";
import TranscriptCard from "./TranscriptCard";
import type { SessionCache } from "../types";
import "./AgentDemo.css";

interface AgentDemoProps {
  sessionId: string | null;
  pendingNew: boolean;
  onSessionCreated: (sid: string) => void;
  cache: SessionCache;
}

export default function AgentDemo({
  sessionId,
  pendingNew,
  onSessionCreated,
  cache,
}: AgentDemoProps) {
  const { question, setQuestion, running, transcripts, handleRun } =
    useAgentStream({ sessionId, pendingNew, onSessionCreated, cache });

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

  return (
    <div className="agent-demo">
      <div className="agent-scroll">
        <div className="agent-scroll-inner">
          {transcripts.map((t) => (
            <TranscriptCard key={t.id} transcript={t} />
          ))}

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
