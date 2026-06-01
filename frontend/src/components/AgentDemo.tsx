import {
  Fragment,
  useState,
  useRef,
  useEffect,
  useCallback,
  useMemo,
} from "react";
import useAgentStream from "../hooks/useAgentStream";
import { FocusProvider } from "../hooks/FocusContext";
import LockableButton from "./LockableButton";
import Icon from "./Icon";
import MessageCard from "./MessageCard";
import ToolPairCard from "./ToolPairCard";
import AgentInput from "./AgentInput";
import EditableUserBubble from "./EditableUserBubble";
import { pairToolCalls } from "../hooks/pairTools";
import { type CommitInfo } from "../types";
import CommitGraphPanel, { CommitGraphHandle } from "./CommitGraphPanel";
import "./AgentDemo.css";

interface AgentDemoProps {
  sessionId: string | null;
  onSessionCreated?: (sid: string) => void;
}

type MessageAction = "delete" | "replay" | null;

// ── Message actions ─────────────────────────────────

function MessageActions({
  locked,
  onDelete,
  onReplay,
}: {
  locked: boolean;
  onDelete: () => void;
  onReplay?: () => void;
}) {
  const [confirming, setConfirming] = useState<MessageAction>(null);
  const actionsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!confirming) return;
    const close = (e: MouseEvent) => {
      if (actionsRef.current && !actionsRef.current.contains(e.target as Node))
        setConfirming(null);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [confirming]);

  const toggle = (a: MessageAction) => {
    if (confirming === a) setConfirming(null);
    else setConfirming(a);
  };

  const confirm = (a: MessageAction) => {
    setConfirming(null);
    if (a === "delete") onDelete();
    else if (a === "replay") onReplay?.();
  };

  return (
    <div className="message-actions" ref={actionsRef}>
      <span className="message-action-trigger">
        <Icon name="dots-vertical" size={12} />
      </span>
      <LockableButton
        icon={<Icon name="trash" size={12} />}
        label="delete"
        confirming={confirming === "delete"}
        locked={locked}
        onToggle={() => toggle("delete")}
        onConfirm={() => confirm("delete")}
      />
      {onReplay && (
        <LockableButton
          icon={<Icon name="replay" size={12} />}
          label="replay"
          confirming={confirming === "replay"}
          locked={locked}
          onToggle={() => toggle("replay")}
          onConfirm={() => confirm("replay")}
        />
      )}
    </div>
  );
}

// ── AgentDemo ───────────────────────────────────────

export default function AgentDemo({
  sessionId,
  onSessionCreated,
}: AgentDemoProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  const {
    running,
    runtimeBusy,
    interrupting,
    messages,
    send,
    interrupt,
    createSession,
    prefillRef,
    reloadMessages,
    truncateMessages,
    resetRunning,
    runError,
    clearRunError,
  } = useAgentStream({
    sessionId,
    onSessionCreated,
    scrollContainerRef: scrollRef,
  });

  const locked = running || runtimeBusy || interrupting;
  const [graphVersion, setGraphVersion] = useState(0);
  const graphRef = useRef<CommitGraphHandle>(null);

  // ── Commit data (session-level, shared with panel and badge) ──
  const [commits, setCommits] = useState<CommitInfo[]>([]);
  const [commitsLoading, setCommitsLoading] = useState(false);
  const [commitsError, setCommitsError] = useState<string | null>(null);

  const fetchCommits = useCallback(
    async (full: boolean) => {
      if (!sessionId) return;
      setCommitsLoading(true);
      setCommitsError(null);
      try {
        const res = await fetch(`/api/session/${sessionId}/commits`);
        if (!res.ok) throw new Error(`Server returned ${res.status}`);
        const data: { commits: CommitInfo[] } = await res.json();
        const items = data.commits || [];
        if (full) {
          const reversed = [...items].reverse();
          setCommits(reversed);
        }
      } catch (err) {
        setCommitsError(err instanceof Error ? err.message : String(err));
        if (full) setCommits([]);
      } finally {
        setCommitsLoading(false);
      }
    },
    [sessionId],
  );

  // Eager fetch on mount / session change
  useEffect(() => {
    if (sessionId) fetchCommits(true);
  }, [sessionId, fetchCommits]);

  const handleRefresh = useCallback(() => fetchCommits(true), [fetchCommits]);

  const handleRemoveFrom = useCallback((sha: string) => {
    setCommits((prev) => {
      const idx = prev.findIndex((c) => c.sha === sha);
      if (idx < 0) return prev;
      return prev.slice(0, idx);
    });
  }, []);

  const handleAppend = useCallback((commit: CommitInfo) => {
    setCommits((prev) => {
      if (prev.some((c) => c.sha === commit.sha)) return prev;
      return [...prev, commit];
    });
  }, []);

  const handleUpdateMessage = useCallback((sha: string, message: string) => {
    setCommits((prev) =>
      prev.map((c) => (c.sha === sha ? { ...c, message } : c)),
    );
  }, []);

  // ── Auto-scroll ──────────────────────────────
  // Our auto-scroll always moves DOWN (scrollTop increases).
  // Any UPWARD movement must be external — no need to guess "who".
  const atBottomRef = useRef(true);
  const prevScrollTopRef = useRef(0);
  const lastScrollRef = useRef(0);

  const scrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scrollToBottom = useCallback((forceSmooth = false) => {
    const el = scrollRef.current;
    if (!el) return;
    const now = performance.now();

    if (scrollTimerRef.current) {
      clearTimeout(scrollTimerRef.current);
      scrollTimerRef.current = null;
    }

    if (forceSmooth) {
      lastScrollRef.current = now;
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
      return;
    }

    // Rapid streaming (<100ms) → skip, wait for pause then smooth catch-up
    if (now - lastScrollRef.current < 100) {
      scrollTimerRef.current = setTimeout(() => {
        scrollTimerRef.current = null;
        lastScrollRef.current = performance.now();
        el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
      }, 100);
      return;
    }

    lastScrollRef.current = now;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, []);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const goingUp = el.scrollTop < prevScrollTopRef.current;
    prevScrollTopRef.current = el.scrollTop;

    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;

    if (distFromBottom <= el.clientHeight * 0.2) {
      atBottomRef.current = true;
    } else if (goingUp) {
      // Only an upward scroll detaches — smooth-animation
      // intermediate frames move down, so they never trigger this.
      atBottomRef.current = false;
    }
  }, []);

  // Streaming content growth → debounced smooth
  useEffect(() => {
    if (atBottomRef.current) {
      scrollToBottom();
    }
  }, [messages, scrollToBottom]);

  // Session switch → always smooth (infrequent event)
  useEffect(() => {
    atBottomRef.current = true;
    scrollToBottom(true);
  }, [sessionId, scrollToBottom]);

  // ── Tool pairing ─────────────────────────────
  const toolPairs = useMemo(() => pairToolCalls(messages, 0), [messages]);

  const pairsByCallId = useMemo(() => {
    const map = new Map<string, (typeof toolPairs)[number][]>();
    for (const p of toolPairs) {
      const arr = map.get(p.callMessageId) || [];
      arr.push(p);
      map.set(p.callMessageId, arr);
    }
    return map;
  }, [toolPairs]);

  const pairedResultIds = useMemo(() => {
    const ids = new Set<string>();
    for (const p of toolPairs) {
      if (p.resultMessage) ids.add(p.resultMessage.id);
    }
    return ids;
  }, [toolPairs]);

  const latestPairKey = toolPairs.length
    ? `${toolPairs[toolPairs.length - 1].callMessageId}/${toolPairs[toolPairs.length - 1].callIndex}`
    : null;

  // ── Click-to-focus (rainbow glow) ───────────
  const [focusedId, setFocusedId] = useState<string | null>(null);

  // ── Commit checkout ──────────────────────────
  const [checkingOut, setCheckingOut] = useState<string | null>(null);
  const [prefillContent, setPrefillContent] = useState("");

  // ── Send handler ─────────────────────────────
  // 所有编排逻辑已移入 useAgentStream.send()，外部只需一行调用

  const handleSend = useCallback(
    (question: string) => {
      send(question);
    },
    [send],
  );

  // ── Independent workspace/message rewind ──────

  interface TruncateOpts {
    commitSha?: string;
    removeSha?: string;
    truncateTid?: string;
    keepTid?: boolean;
    sendContent?: string;
  }

  const applyTruncate = useCallback(
    async (opts: TruncateOpts) => {
      if (!sessionId) return;

      // interrupt() is idempotent — no-op if nothing is running
      await interrupt();
      resetRunning();

      if (opts.commitSha) setCheckingOut(opts.commitSha);

      try {
        if (opts.commitSha) {
          await fetch(`/api/session/${sessionId}/workspace/restore`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              commit_sha: opts.commitSha,
              set_head: true,
            }),
          });
        }
        if (opts.truncateTid) {
          await fetch(`/api/session/${sessionId}/messages/truncate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              message_id: opts.truncateTid,
              keep: opts.keepTid || false,
            }),
          });
        }
      } catch {}

      if (opts.truncateTid) truncateMessages(opts.truncateTid, !!opts.keepTid);
      if (opts.removeSha) handleRemoveFrom(opts.removeSha);

      // send() internally handles session creation, interrupt, and streaming
      if (opts.sendContent && sessionId) {
        await send(opts.sendContent);
      }

      if (opts.commitSha) setCheckingOut(null);
    },
    [
      sessionId,
      interrupt,
      resetRunning,
      truncateMessages,
      handleRemoveFrom,
      send,
    ],
  );

  const handleEditSubmit = useCallback(
    (tid: string, content: string) => {
      applyTruncate({
        truncateTid: tid,
        keepTid: false,
        sendContent: content,
      });
    },
    [applyTruncate],
  );

  // ── Deprecated handlers (kept for CommitGraphPanel) ──

  const handleCheckout = useCallback(
    async (checkoutSha: string, removeSha?: string) => {
      applyTruncate({
        commitSha: checkoutSha,
        removeSha,
      });
    },
    [applyTruncate],
  );

  const handleCheckoutKeep = useCallback(
    async (checkoutSha: string, removeSha?: string) => {
      applyTruncate({
        commitSha: checkoutSha,
        removeSha,
      });
    },
    [applyTruncate],
  );

  return (
    <div className="agent-demo">
      <div className="agent-scroll" ref={scrollRef} onScroll={handleScroll}>
        <div className="agent-scroll-center">
          <FocusProvider focusedId={focusedId}>
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
              {messages.map((t) => {
                if (pairedResultIds.has(t.id)) return null;
                const pairs = pairsByCallId.get(t.id);
                if (pairs) {
                  return (
                    <Fragment key={t.id}>
                      {t.role === "assistant" && (
                        <div className="assistant-splitter" />
                      )}
                      <span key={t.id} data-message-id={t.id}>
                        <MessageCard message={t} hideToolCards />
                      </span>
                      {pairs.map((pair) => (
                        <ToolPairCard
                          key={`${pair.callMessageId}/${pair.callIndex}`}
                          pair={pair}
                          defaultCollapsed={
                            latestPairKey !==
                            `${pair.callMessageId}/${pair.callIndex}`
                          }
                        />
                      ))}
                    </Fragment>
                  );
                }
                if (t.role === "user") {
                  const content = t.content || "";
                  return (
                    <div
                      key={t.id}
                      className="user-bubble-wrapper"
                      data-message-id={t.id}
                    >
                      <EditableUserBubble
                        content={content}
                        onEditSubmit={(c) => handleEditSubmit(t.id, c)}
                      />
                      <MessageActions
                        locked={locked}
                        onDelete={() =>
                          applyTruncate({
                            truncateTid: t.id,
                            keepTid: false,
                          })
                        }
                        onReplay={() =>
                          applyTruncate({
                            truncateTid: t.id,
                            keepTid: false,
                            sendContent: content,
                          })
                        }
                      />
                    </div>
                  );
                }
                return (
                  <span key={t.id} data-message-id={t.id}>
                    {t.role === "assistant" && (
                      <div className="assistant-splitter" />
                    )}
                    <MessageCard message={t} />
                  </span>
                );
              })}

              <div className="agent-bottom-spacer" />
            </div>
          </FocusProvider>
        </div>
      </div>

      {runError && (
        <div className="agent-run-error" role="alert">
          <span>{runError}</span>
          <button
            type="button"
            className="agent-run-error-dismiss"
            aria-label="关闭"
            onClick={clearRunError}
          >
            ×
          </button>
        </div>
      )}

      <AgentInput
        running={running}
        runtimeBusy={runtimeBusy}
        interrupting={interrupting}
        prefillRef={prefillRef}
        prefillContent={prefillContent}
        onPrefillChange={setPrefillContent}
        onSend={handleSend}
        onInterrupt={interrupt}
      />

      <CommitGraphPanel
        ref={graphRef}
        commits={commits}
        loading={commitsLoading}
        error={commitsError}
        locked={locked}
        onRefresh={handleRefresh}
        onRemoveFrom={handleRemoveFrom}
        onAppend={handleAppend}
        onUpdateMessage={handleUpdateMessage}
        onCheckout={handleCheckout}
        onCheckoutKeep={handleCheckoutKeep}
      />
    </div>
  );
}
