import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import useAgentStream from "../hooks/useAgentStream";
import Icon from "./Icon";
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

function CommitBadge({
  shortSha,
  commitSha,
  onCheckout,
}: {
  shortSha: string;
  commitSha: string;
  onCheckout: (sha: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  return (
    <div className="commit-badge">
      <span className="commit-short-id">{shortSha}</span>
      {confirming ? (
        <span
          className="commit-restore commit-restore--confirm"
          onClick={(e) => {
            e.stopPropagation();
            setConfirming(false);
            onCheckout(commitSha);
          }}
        >
          <Icon name="restore" size={12} />
          confirm
        </span>
      ) : (
        <span
          className="commit-restore"
          onClick={(e) => {
            e.stopPropagation();
            setConfirming(true);
          }}
        >
          <Icon name="restore" size={12} />
          restore
        </span>
      )}
    </div>
  );
}

export default function AgentDemo({
  sessionId,
  pendingNew,
  onSessionCreated,
  cache,
}: AgentDemoProps) {
  const { question, setQuestion, running, interrupting, transcripts, handleRun, prefillRef, reloadTranscripts, handleInterrupt } =
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
  const toolPairs = useMemo(() => pairToolCalls(transcripts, 0), [transcripts]);

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

  // ── Click-to-focus (rainbow glow) ───────────
  const [focusedId, setFocusedId] = useState<string | null>(null);

  // Toggle card-latest class via data-fid attribute
  useEffect(() => {
    document
      .querySelectorAll(".card-latest")
      .forEach((el) => el.classList.remove("card-latest"));
    if (focusedId) {
      document
        .querySelectorAll(`[data-fid="${focusedId}"]`)
        .forEach((el) => el.classList.add("card-latest"));
    }
  }, [focusedId]);
  const focusElement = useCallback((id: string) => {
    setFocusedId(id);
  }, []);

  // ── Commit checkout ──────────────────────────
  const [checkingOut, setCheckingOut] = useState<string | null>(null);
  const [prefillContent, setPrefillContent] = useState("");
  const handleCheckout = useCallback(
    async (commitSha: string) => {
      if (!sessionId || checkingOut) return;
      setCheckingOut(commitSha);
      try {
        const res = await fetch(
          `/api/session/${sessionId}/checkout`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ commit_sha: commitSha }),
          },
        );
        if (!res.ok) throw new Error(`Server returned ${res.status}`);
        const data = await res.json();
        if (data.user_content) {
          setPrefillContent(data.user_content);
        }
        reloadTranscripts();
      } catch (err) {
        console.error("Checkout failed", err);
      } finally {
        setCheckingOut(null);
      }
    },
    [sessionId, checkingOut],
  );

  // ── Input handlers ───────────────────────────

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter") {
      if (e.ctrlKey || e.metaKey || e.shiftKey) return;
      if (composingRef.current) return;
      e.preventDefault();
      if (prefillContent.trim()) {
        prefillRef.current = prefillContent.trim();
        setPrefillContent("");
      }
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
        <div className="agent-scroll-center">
        <div
          className="agent-scroll-inner"
          onClick={(e) => {
            const el = (e.target as HTMLElement).closest("[data-fid]");
            if (el) {
              const fid = el.getAttribute("data-fid");
              if (fid) setFocusedId(fid);
            }
          }}
        >
          {transcripts.map((t) => {
            // Result consumed by a pair — skip
            if (pairedResultIds.has(t.id)) return null;
            // Call transcript with tool pairs — render both with click-to-focus
            const pairs = pairsByCallId.get(t.id);
            if (pairs) {
              return (
                <>
                  {t.kind === "assistant" && (
                    <div className="assistant-splitter" />
                  )}
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
                </>
              );
            }
            // Regular transcript — user bubbles need to be direct flex children
            if (t.kind === "user_question") {
              const commitSha = t.commitSha;
              const shortSha = commitSha ? commitSha.slice(0, 7) : null;
              return (
                <div key={t.id} className="user-bubble-wrapper">
                  <TranscriptCard transcript={t} />
                  {shortSha && (
                    <CommitBadge
                      shortSha={shortSha}
                      commitSha={commitSha!}
                      onCheckout={handleCheckout}
                    />
                  )}
                </div>
              );
            }
            return (
              <span key={t.id}>
                {t.kind === "assistant" && (
                  <div className="assistant-splitter" />
                )}
                <TranscriptCard transcript={t} />
              </span>
            );
          })}

          <div className="agent-bottom-spacer" />
        </div>
        </div>
      </div>

      <div className={`agent-prefill${prefillContent.trim() ? " agent-prefill--open" : ""}`}>
        <div className="agent-prefill-inner">
        <textarea
          className="agent-prefill-textarea"
          placeholder="(prefix)"
          value={prefillContent}
          onChange={(e) => setPrefillContent(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
              e.preventDefault();
              if (prefillContent.trim()) {
                prefillRef.current = prefillContent.trim();
                setPrefillContent("");
                handleRun();
              }
            }
          }}
          rows={1}
        />
        <button
          className="agent-prefill-close"
          onClick={() => setPrefillContent("")}
        >
          ×
        </button>
        </div>
      </div>
      <div className="agent-input-bar">
        <div className="agent-input-bar-inner">
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
          className={
            interrupting
              ? "agent-send-btn agent-send-btn--stopping"
              : running
                ? "agent-send-btn agent-send-btn--stop"
                : "agent-send-btn"
          }
          onClick={running && !interrupting ? handleInterrupt : handleRun}
          disabled={interrupting || (!running && !question.trim() && !prefillContent.trim())}
        >
          {interrupting ? "Stopping…" : running ? "Stop" : "Send"}
        </button>
        </div>
      </div>
    </div>
  );
}
