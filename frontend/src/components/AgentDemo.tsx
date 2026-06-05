import {
  Fragment,
  useState,
  useRef,
  useEffect,
  useLayoutEffect,
  useCallback,
  useMemo,
} from "react";
import type { ChangeEvent } from "react";
import useAgentStream from "../hooks/useAgentStream";
import { FocusProvider } from "../hooks/FocusContext";
import LockableButton from "./LockableButton";
import Icon from "./Icon";
import MessageCard from "./MessageCard";
import ToolPairCard from "./ToolPairCard";
import AgentInput from "./AgentInput";
import EditableUserBubble from "./EditableUserBubble";
import NoticeHost from "./NoticeHost";
import { pairToolCalls } from "../hooks/pairTools";
import {
  type CommitInfo,
  type CreateSessionRequest,
  type GuardRequest,
} from "../types";
import CommitGraphPanel, { CommitGraphHandle } from "./CommitGraphPanel";
import "./AgentDemo.css";

interface AgentDemoProps {
  sessionId: string | null;
  onSessionCreated?: (sid: string) => void;
}

type MessageAction = "delete" | "replay" | null;

function useOverlayStackMotion() {
  const ref = useRef<HTMLDivElement>(null);
  const previousRectsRef = useRef<Map<string, DOMRect>>(new Map());
  const previousSignatureRef = useRef("");

  useLayoutEffect(() => {
    const root = ref.current;
    if (!root) return;

    const nextRects = new Map<string, DOMRect>();
    const items = Array.from(
      root.querySelectorAll<HTMLElement>("[data-overlay-item]"),
    );
    const signature = items
      .map((item) => item.dataset.overlayItem || "")
      .join("|");
    const shouldAnimateLayout =
      previousSignatureRef.current !== "" &&
      previousSignatureRef.current !== signature;

    for (const item of items) {
      const key = item.dataset.overlayItem;
      if (!key) continue;
      const next = item.getBoundingClientRect();
      const previous = previousRectsRef.current.get(key);
      nextRects.set(key, next);

      if (!previous) continue;
      const dy = previous.top - next.top;
      if (!shouldAnimateLayout || Math.abs(dy) < 0.5) continue;

      item.animate(
        [
          { transform: `translateY(${dy}px)` },
          { transform: "translate(0, 0)" },
        ],
        {
          duration: 260,
          easing: "cubic-bezier(0.16, 1, 0.3, 1)",
        },
      );
    }

    previousRectsRef.current = nextRects;
    previousSignatureRef.current = signature;
  });

  return ref;
}

function PendingRequestPanel({
  request,
  onRespond,
}: {
  request: GuardRequest;
  onRespond: (
    requestId: string,
    response: Record<string, unknown>,
  ) => Promise<void>;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [custom, setCustom] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});

  if (request.kind !== "user_input_request") {
    return (
      <div
        className="agent-guard-request"
        role="alert"
        data-overlay-item={`pending-${request.request_id}`}
      >
        <div className="agent-guard-main">
          <span className="agent-guard-kicker">Permission Required</span>
          <span className="agent-guard-text">
            {request.action_type}: {request.subject}
          </span>
        </div>
        <div className="agent-guard-actions">
          <button
            className="agent-guard-deny"
            type="button"
            onClick={() => void onRespond(request.request_id, { allow: false })}
          >
            <Icon name="x" size={13} />
            Deny
          </button>
          <button
            className="agent-guard-allow"
            type="button"
            onClick={() => void onRespond(request.request_id, { allow: true })}
          >
            <Icon name="check" size={13} />
            Allow
          </button>
        </div>
      </div>
    );
  }

  const payload = request.payload || {};
  const title =
    request.title || String(payload.title || "") || request.subject || "Input requested";
  const description = request.description || String(payload.description || "");
  const choices =
    request.choices ||
    (payload.choices as GuardRequest["choices"]) ||
    [];
  const questions =
    request.questions || (payload.questions as GuardRequest["questions"]) || [];
  const allowCustom =
    request.allow_custom ?? Boolean(payload.allow_custom || false);
  const choiceRequired =
    request.choice_required ??
    (payload.choice_required == null ? true : Boolean(payload.choice_required));
  const multiple = request.multiple ?? Boolean(payload.multiple || false);
  const qaValid = questions.every(
    (q) => !q.required || (answers[q.id] || "").trim(),
  );
  const choiceValid =
    !choices.length ||
    !choiceRequired ||
    selected.length > 0 ||
    Boolean(custom.trim());
  const canSubmit = choiceValid && qaValid;

  const submit = () => {
    if (!canSubmit) return;
    void onRespond(request.request_id, {
      selected,
      custom: custom.trim(),
      answers,
    });
  };

  const ignore = () => {
    void onRespond(request.request_id, {
      ignored: true,
      reason: "user_ignored",
    });
  };

  const toggleChoice = (id: string) => {
    setSelected((prev) => {
      if (!multiple) return prev.includes(id) ? [] : [id];
      return prev.includes(id)
        ? prev.filter((item) => item !== id)
        : [...prev, id];
    });
  };

  return (
    <div
      className="agent-guard-request agent-user-request"
      role="alert"
      data-overlay-item={`pending-${request.request_id}`}
    >
      <div className="agent-guard-main agent-user-request-main">
        <span className="agent-guard-kicker">Input Requested</span>
        <span className="agent-guard-text">{title}</span>
        {description && (
          <span className="agent-user-request-description">{description}</span>
        )}

        <div className="agent-user-request-body">
          {choices.length > 0 && (
            <div className="agent-user-choice-list">
              {choices.map((option) => (
                <label
                  className="agent-user-choice"
                  key={option.id}
                  data-selected={selected.includes(option.id)}
                >
                  <input
                    type={multiple ? "checkbox" : "radio"}
                    name={`ask-user-${request.request_id}`}
                    checked={selected.includes(option.id)}
                    onChange={() => toggleChoice(option.id)}
                  />
                  <span>
                    <strong>{option.label}</strong>
                    {option.description && <small>{option.description}</small>}
                  </span>
                </label>
              ))}
              {allowCustom && (
                <input
                  className="agent-user-input"
                  placeholder="Custom response"
                  value={custom}
                  onChange={(e) => setCustom(e.target.value)}
                />
              )}
            </div>
          )}

          {questions.length > 0 && (
            <div className="agent-user-qa-list">
              {questions.map((question) => {
                const common = {
                  value: answers[question.id] || "",
                  placeholder: question.placeholder || "",
                  onChange: (
                    e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
                  ) =>
                    setAnswers((prev) => ({
                      ...prev,
                      [question.id]: e.target.value,
                    })),
                };
                return (
                  <label className="agent-user-question" key={question.id}>
                    <span>
                      {question.label}
                      {question.required ? " *" : ""}
                    </span>
                    {question.type === "textarea" ? (
                      <textarea {...common} rows={3} />
                    ) : (
                      <input {...common} />
                    )}
                  </label>
                );
              })}
            </div>
          )}
        </div>
      </div>
      <div className="agent-guard-actions agent-user-request-actions">
        <button
          className="agent-user-ignore"
          type="button"
          title="Ignore this request: I do not want to answer."
          onClick={ignore}
        >
          Ignore
        </button>
        <button
          className="agent-guard-allow"
          type="button"
          disabled={!canSubmit}
          onClick={submit}
        >
          <Icon name="check" size={13} />
          Submit
        </button>
      </div>
    </div>
  );
}

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
  const overlayStackRef = useOverlayStackMotion();

  const {
    running,
    runtimeBusy,
    interrupting,
    messages,
    send,
    interrupt,
    respondPending,
    prefillRef,
    reloadMessages,
    truncateMessages,
    resetRunning,
    pendingGuard,
    notices,
    dismissNotice,
  } = useAgentStream({
    sessionId,
    onSessionCreated,
    scrollContainerRef: scrollRef,
  });

  const locked = running || runtimeBusy || interrupting;
  const [sessionConfig, setSessionConfig] = useState<CreateSessionRequest>({
    name: "",
    preamble: "",
    rules: [],
    preloaded_skills: [],
    tool_set_preset: "all",
    custom_tools: [],
  });
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

  const pairedResultToolCallIds = useMemo(() => {
    const ids = new Set<string>();
    for (const p of toolPairs) {
      if (p.resultMessage && p.toolCall.id) ids.add(p.toolCall.id);
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
      send(question, sessionId ? undefined : sessionConfig);
    },
    [send, sessionId, sessionConfig],
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
                if (
                  t.role === "tool" &&
                  t.tool_call_id &&
                  pairedResultToolCallIds.has(t.tool_call_id)
                ) {
                  return null;
                }
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

      {(notices.length > 0 || pendingGuard) && (
        <div
          className="agent-overlay-stack"
          ref={overlayStackRef}
          aria-live="polite"
          aria-atomic="false"
        >
          <NoticeHost notices={notices} onDismiss={dismissNotice} />
          {pendingGuard && (
            <PendingRequestPanel
              request={pendingGuard}
              onRespond={respondPending}
            />
          )}
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
        sessionConfig={sessionConfig}
        onSessionConfigChange={setSessionConfig}
        showCustomize
        customizeReadonly={!!sessionId || messages.length > 0}
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
