import {
  useState,
  useEffect,
  useRef,
  forwardRef,
  useImperativeHandle,
} from "react";
import Icon from "./Icon";
import LockableButton from "./LockableButton";
import type { CommitInfo } from "../types";

export interface CommitGraphHandle {
  removeFrom: (sha: string) => void;
  append: (commit: CommitInfo) => void;
  updateMessage: (sha: string, message: string) => void;
  refresh: () => void;
}

interface CommitGraphPanelProps {
  commits: CommitInfo[];
  loading: boolean;
  error: string | null;
  locked: boolean;
  onRefresh: () => void;
  onRemoveFrom: (sha: string) => void;
  onAppend: (commit: CommitInfo) => void;
  onUpdateMessage: (sha: string, message: string) => void;
  onCheckout: (sha: string, removeSha?: string) => void;
  onCheckoutKeep: (sha: string, removeSha?: string) => void;
}

const CommitGraphPanel = forwardRef<CommitGraphHandle, CommitGraphPanelProps>(
  function CommitGraphPanel(
    {
      commits,
      loading,
      error,
      locked,
      onRefresh,
      onRemoveFrom,
      onAppend,
      onUpdateMessage,
      onCheckout,
      onCheckoutKeep,
    },
    ref,
  ) {
    // Panel open state
    const [open, setOpen] = useState(false);
    const [hoveredSha, setHoveredSha] = useState<string | null>(null);
    const [confirming, setConfirming] = useState<string | null>(null);
    const [newSha, setNewSha] = useState<string | null>(null);
    const [removingShas, setRemovingShas] = useState<Set<string>>(new Set());
    const hoverRef = useRef(false);
    const focusRef = useRef(false);
    const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const wrapperRef = useRef<HTMLDivElement | null>(null);

    // ── Animated display commits (lag behind props for shrink/grow) ──
    const [displayCommits, setDisplayCommits] = useState<CommitInfo[]>(commits);
    const prevCommitsRef = useRef<CommitInfo[]>(commits);
    const latestCommitsRef = useRef<CommitInfo[]>(commits);
    const animTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // Always keep latest commits accessible from timer closures
    latestCommitsRef.current = commits;

    // Sync commits prop → displayCommits with animation delays
    useEffect(() => {
      const prev = prevCommitsRef.current;
      const prevShas = new Set(prev.map((c) => c.sha));
      const currShas = new Set(commits.map((c) => c.sha));

      const removedShasArr = prev
        .filter((c) => !currShas.has(c.sha))
        .map((c) => c.sha);
      const addedArr = commits.filter((c) => !prevShas.has(c.sha));

      // Full refresh (e.g. session switch) — skip animations
      const isFullRefresh =
        prev.length > 0 &&
        prev.every((c) => !currShas.has(c.sha)) &&
        commits.every((c) => !prevShas.has(c.sha));

      if (isFullRefresh) {
        setDisplayCommits(commits);
        setNewSha(null);
        setRemovingShas(new Set());
        if (animTimerRef.current) {
          clearTimeout(animTimerRef.current);
          animTimerRef.current = null;
        }
        prevCommitsRef.current = commits;
        return;
      }

      // ── Removals: add to removingShas, delay actual removal ──
      if (removedShasArr.length > 0) {
        // Cancel any pending grow animation
        if (animTimerRef.current) {
          clearTimeout(animTimerRef.current);
          animTimerRef.current = null;
        }
        setNewSha(null);

        setRemovingShas((prev_) => {
          const next = new Set(prev_);
          removedShasArr.forEach((sha) => next.add(sha));
          return next;
        });
        // Keep displayCommits unchanged during shrink animation.
        // Timer uses latestCommitsRef to pick up any message updates
        // that arrived after the removal.
        animTimerRef.current = setTimeout(() => {
          setDisplayCommits(latestCommitsRef.current);
          setRemovingShas(new Set());
          animTimerRef.current = null;
        }, 200);
        prevCommitsRef.current = commits;
        return;
      }

      // ── Additions: immediately show, mark newSha for grow animation ──
      if (addedArr.length > 0) {
        // If a shrink animation is pending, force-complete it now
        // so displayCommits reflects reality before adding.
        if (animTimerRef.current) {
          clearTimeout(animTimerRef.current);
          animTimerRef.current = null;
          // Complete the pending removal synchronously
          setDisplayCommits(latestCommitsRef.current);
          setRemovingShas(new Set());
        }
        setDisplayCommits(commits);
        if (addedArr.length === 1) {
          setNewSha(addedArr[0].sha);
          animTimerRef.current = setTimeout(() => {
            setNewSha(null);
            animTimerRef.current = null;
          }, 250);
        }
        prevCommitsRef.current = commits;
        return;
      }

      // ── In-place update (e.g. message change) ──
      // Merge updated messages without disturbing animation state.
      // If an animation is active the removed / new nodes are already
      // handled above; here we only propagate message changes.
      setDisplayCommits((prevDisplay) =>
        prevDisplay.map((dc) => {
          const fresh = commits.find((c) => c.sha === dc.sha);
          return fresh ? { ...dc, message: fresh.message } : dc;
        }),
      );
      prevCommitsRef.current = commits;

      // Cleanup animation timer on unmount
      return () => {
        if (animTimerRef.current) {
          clearTimeout(animTimerRef.current);
          animTimerRef.current = null;
        }
      };
    }, [commits]);

    const tryOpen = () => {
      if (closeTimerRef.current) {
        clearTimeout(closeTimerRef.current);
        closeTimerRef.current = null;
      }
      const wasClosed = !open;
      setOpen(true);
      if (wasClosed) {
        onRefresh();
      }
    };
    const tryClose = () => {
      if (closeTimerRef.current) clearTimeout(closeTimerRef.current);
      closeTimerRef.current = setTimeout(() => {
        if (!hoverRef.current && !focusRef.current) setOpen(false);
      }, 200);
    };

    useEffect(() => {
      const el = wrapperRef.current;
      if (!el) return;
      const onFocusIn = () => {
        focusRef.current = true;
        tryOpen();
      };
      const onFocusOut = () => {
        focusRef.current = false;
        tryClose();
      };
      el.addEventListener("focusin", onFocusIn);
      el.addEventListener("focusout", onFocusOut);
      return () => {
        el.removeEventListener("focusin", onFocusIn);
        el.removeEventListener("focusout", onFocusOut);
      };
    }, []);

    // ── imperative API (delegates to AgentDemo) ──

    useImperativeHandle(
      ref,
      () => ({
        removeFrom: onRemoveFrom,
        append: onAppend,
        updateMessage: onUpdateMessage,
        refresh: onRefresh,
      }),
      [onRemoveFrom, onAppend, onUpdateMessage, onRefresh],
    );

    // ── helpers ────────────────────────────────

    const formatTime = (unix: number) => {
      const d = new Date(unix * 1000);
      const pad = (n: number) => String(n).padStart(2, "0");
      return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    };

    // ── render ─────────────────────────────────

    return (
      <div
        ref={wrapperRef}
        className="commit-graph-wrapper"
        onMouseEnter={() => {
          hoverRef.current = true;
          tryOpen();
        }}
        onMouseLeave={() => {
          hoverRef.current = false;
          tryClose();
        }}
      >
        <button
          className="commit-graph-toggle"
          onClick={(e) => {
            e.stopPropagation();
            open ? tryClose() : tryOpen();
          }}
          title={open ? "Hide history" : "Show history"}
        >
          <Icon name="git-graph" size={14} />
        </button>
        <div
          className={`commit-graph-panel${!open ? " commit-graph-panel--closed" : ""}`}
          tabIndex={-1}
        >
          <div className="commit-graph-header">
            <span className="commit-graph-title">History</span>
          </div>
          <div className="commit-graph-body">
            {loading && <div className="commit-graph-status">Loading…</div>}
            {error && (
              <div className="commit-graph-status commit-graph-status--error">
                {error}
              </div>
            )}
            {!loading && !error && displayCommits.length === 0 && (
              <div className="commit-graph-status">No commits yet</div>
            )}
            <div className="commit-graph-list">
              {displayCommits.map((c, i) => {
                const hasParent = i > 0;
                const hasNext = i < displayCommits.length - 1;
                const makeActions = (action: string, onAction: () => void) => ({
                  confirming: confirming === c.sha + "/" + action,
                  onToggle: () =>
                    setConfirming(
                      confirming === c.sha + "/" + action
                        ? null
                        : c.sha + "/" + action,
                    ),
                  onConfirm: () => {
                    setConfirming(null);
                    onAction();
                  },
                });

                return (
                  <div
                    key={c.sha}
                    className={`commit-node${newSha === c.sha ? " commit-node--new" : ""}${removingShas.has(c.sha) ? " commit-node--removing" : ""}`}
                    onMouseEnter={() => setHoveredSha(c.sha)}
                    onMouseLeave={() => {
                      setHoveredSha(null);
                      setConfirming(null);
                    }}
                  >
                    <div
                      className={`commit-node-actions${hoveredSha === c.sha ? " commit-node-actions--show" : ""}`}
                    >
                      {hasParent && (
                        <LockableButton
                          icon={<Icon name="undo" size={11} />}
                          label="regret"
                          locked={locked}
                          {...makeActions("regret", () =>
                            onCheckout(displayCommits[i - 1].sha, c.sha),
                          )}
                        />
                      )}
                      <LockableButton
                        icon={<Icon name="flag" size={11} />}
                        label="restore"
                        locked={locked}
                        {...makeActions("restore", () =>
                          onCheckoutKeep(
                            c.sha,
                            hasNext ? displayCommits[i + 1].sha : undefined,
                          ),
                        )}
                      />
                    </div>
                    <div className="commit-node-line">
                      <div className="commit-node-dot" />
                      {i < displayCommits.length - 1 && (
                        <div className="commit-node-trail" />
                      )}
                    </div>
                    <div className="commit-node-body" title="Workspace commit">
                      <span className="commit-node-sha">{c.short_sha}</span>
                      <span className="commit-node-msg" title={c.message}>
                        {c.message}
                      </span>
                      <span className="commit-node-time">
                        {formatTime(c.author_time)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    );
  },
);

export default CommitGraphPanel;
