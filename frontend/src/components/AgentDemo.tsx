import { useState, useRef } from "react";
import useAgentStream from "../hooks/useAgentStream";
import Markdown from "./Markdown";
import type { DisplayTranscript, SessionCache } from "../types";
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
  const { question, setQuestion, running, transcripts, answer, handleRun } =
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
          {transcripts.map((t) => {
            const isUser = t.kind === "user_question";
            const content = String(t.message.content || t.pendingChunks || "");
            const isStreaming = !t.isFlushed && t.pendingChunks;

            if (isUser) {
              return (
                <div key={t.id} className="user-bubble">
                  <span className="user-bubble-label">You</span>
                  <p>{content}</p>
                </div>
              );
            }

            // Assistant / tool / error transcripts
            const label =
              t.kind === "tool_result"
                ? "\uD83D\uDD27 Tool"
                : t.kind === "assistant"
                  ? "\uD83D\uDCAC Assistant"
                  : t.kind === "error"
                    ? "\u26A0\uFE0F Error"
                    : t.kind;

            return (
              <div
                key={t.id}
                className={`transcript-card ${isStreaming ? "streaming" : ""}`}
              >
                <span className="transcript-label">{label}</span>
                <div className="transcript-body">
                  {t.kind === "tool_result" ? (
                    <pre>
                      {content.length > 500
                        ? content.slice(0, 500) + "..."
                        : content}
                    </pre>
                  ) : (
                    <Markdown text={content} />
                  )}
                </div>
              </div>
            );
          })}

          {answer && (
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
