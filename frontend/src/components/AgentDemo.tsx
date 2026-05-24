import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import useAgentStream from "../hooks/useAgentStream";
import TranscriptCard from "./TranscriptCard";
import ToolPairCard from "./ToolPairCard";
import { pairToolCalls } from "../hooks/pairTools";
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

  // ── Auto-scroll ──────────────────────────────
  const scrollRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);
  const scrollingRef = useRef(false);

  const scrollToBottom = useCallback(() => {
    scrollingRef.current = true;
    requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (el) {
        el.scrollTop = el.scrollHeight;
      }
      requestAnimationFrame(() => {
        scrollingRef.current = false;
      });
    });
  }, []);

  const handleScroll = useCallback(() => {
    if (scrollingRef.current) return;
    const el = scrollRef.current;
    if (!el) return;
    const threshold = 40;
    atBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
  }, []);

  useEffect(() => {
    if (atBottomRef.current) {
      scrollToBottom();
    }
  }, [transcripts, scrollToBottom]);

  useEffect(() => {
    atBottomRef.current = true;
    scrollToBottom();
  }, [sessionId, scrollToBottom]);

  // ── Tool pairing ─────────────────────────────
  const toolPairs = useMemo(
    () => pairToolCalls(transcripts, 0),
    [transcripts],
  );

  // Group pairs by callTranscriptId for interleaved rendering
  const pairsByCallId = useMemo(() => {
    const map = new Map<string, (typeof toolPairs)[number][]>();
    for (const p of toolPairs) {
      const arr = map.get(p.callTranscriptId) || [];
      arr.push(p);
      map.set(p.callTranscriptId, arr);
    }
    return map;
  }, [toolPairs]);

  // IDs of result transcripts consumed by a pair
  const pairedResultIds = useMemo(() => {
    const ids = new Set<string>();
    for (const p of toolPairs) {
      if (p.result) ids.add(p.result.id);
    }
    return ids;
  }, [toolPairs]);

  // The latest pair stays expanded; older ones default to collapsed
  const latestPairKey = toolPairs.length
    ? `${toolPairs[toolPairs.length - 1].callTranscriptId}/${toolPairs[toolPairs.length - 1].callIndex}`
    : null;

  // ── Input handlers ───────────────────────────

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
      <div className="agent-scroll" ref={scrollRef} onScroll={handleScroll}>
        <div className="agent-scroll-inner">
          {transcripts.map((t) => {
            // Result consumed by a pair — skip
            if (pairedResultIds.has(t.id)) return null;
            // Call transcript with tool pairs — render both
            const pairs = pairsByCallId.get(t.id);
            if (pairs) {
              return (
                <span key={t.id}>
                  <TranscriptCard transcript={t} hideToolCards />
                  {pairs.map((pair) => (
                    <ToolPairCard
                      key={`${pair.callTranscriptId}/${pair.callIndex}`}
                      pair={pair}
                      defaultCollapsed={
                        latestPairKey !==
                        `${pair.callTranscriptId}/${pair.callIndex}`
                      }
                    />
                  ))}
                </span>
              );
            }
            // Regular transcript
            return <TranscriptCard key={t.id} transcript={t} />;
          })}

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
