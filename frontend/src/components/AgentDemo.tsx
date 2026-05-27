import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import useAgentStream from "../hooks/useAgentStream";
import { FocusProvider } from "../hooks/FocusContext";
import LockableButton from "./LockableButton";
import Icon from "./Icon";
import TranscriptCard from "./TranscriptCard";
import ToolPairCard from "./ToolPairCard";
import AgentInput from "./AgentInput";
import EditableUserBubble from "./EditableUserBubble";
import { pairToolCalls } from "../hooks/pairTools";
import { getCommitActions, type SessionCache, type CommitInfo } from "../types";
import CommitGraphPanel, { CommitGraphHandle } from "./CommitGraphPanel";
import "./AgentDemo.css";

interface AgentDemoProps {
    sessionId: string | null;
    pendingNew: boolean;
    onSessionCreated: (sid: string) => void;
    cache: SessionCache;
}

type CommitAction = "regret" | "restore" | "replay" | null;

// ── Commit badge ────────────────────────────────────

function CommitBadge({
    shortSha,
    locked,
    onRegret,
    onRestore,
    onReplay,
}: {
    shortSha: string;
    locked: boolean;
    onRegret?: () => void;
    onRestore?: () => void;
    onReplay?: () => void;
}) {
    const [confirming, setConfirming] = useState<CommitAction>(null);
    const badgeRef = useRef<HTMLDivElement>(null);
    useEffect(() => {
        if (!confirming) return;
        const close = (e: MouseEvent) => {
            if (
                badgeRef.current &&
                !badgeRef.current.contains(e.target as Node)
            )
                setConfirming(null);
        };
        document.addEventListener("mousedown", close);
        return () => document.removeEventListener("mousedown", close);
    }, [confirming]);

    const toggle = (a: CommitAction) => {
        if (confirming === a) setConfirming(null);
        else setConfirming(a);
    };

    const confirm = (a: CommitAction) => {
        setConfirming(null);
        if (a === "regret") onRegret?.();
        else if (a === "restore") onRestore?.();
        else if (a === "replay") onReplay?.();
    };

    return (
        <div className="commit-badge" ref={badgeRef}>
            <span className="commit-short-id">{shortSha}</span>
            {onRegret && (
                <LockableButton
                    icon={<Icon name="undo" size={12} />}
                    label="regret"
                    confirming={confirming === "regret"}
                    locked={locked}
                    onToggle={() => toggle("regret")}
                    onConfirm={() => confirm("regret")}
                />
            )}
            {onRestore && (
                <LockableButton
                    icon={<Icon name="flag" size={12} />}
                    label="restore"
                    confirming={confirming === "restore"}
                    locked={locked}
                    onToggle={() => toggle("restore")}
                    onConfirm={() => confirm("restore")}
                />
            )}
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
    pendingNew,
    onSessionCreated,
    cache,
}: AgentDemoProps) {
    const scrollRef = useRef<HTMLDivElement>(null);

    const {
        running,
        interrupting,
        transcripts,
        handleRun,
        prefillRef,
        reloadTranscripts,
        truncateTranscripts,
        handleInterrupt,
        resetRunning,
        scrollToTranscript,
    } = useAgentStream({
        sessionId,
        pendingNew,
        onSessionCreated,
        cache,
        scrollContainerRef: scrollRef,
        onCommit: (targetTid: string, commitSha: string) => {
            const t = transcripts.find((item) => item.id === targetTid);
            const content = t
                ? String((t.message as Record<string, unknown>).content || "")
                : "";
            handleAppend({
                sha: commitSha,
                short_sha: commitSha.slice(0, 7),
                message: content || "(no message)",
                author_time: Date.now() / 1000,
                transcript_id: targetTid,
            });
        },
    });

    const locked = running || interrupting;
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
                setCommitsError(
                    err instanceof Error ? err.message : String(err),
                );
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

    const scrollToBottom = useCallback((forceSmooth = false) => {
        const el = scrollRef.current;
        if (!el) return;
        const now = performance.now();
        const useSmooth = forceSmooth || now - lastScrollRef.current > 100;
        lastScrollRef.current = now;
        el.scrollTo({
            top: el.scrollHeight,
            behavior: useSmooth ? "smooth" : "auto",
        });
    }, []);

    const handleScroll = useCallback(() => {
        const el = scrollRef.current;
        if (!el) return;
        const goingUp = el.scrollTop < prevScrollTopRef.current;
        prevScrollTopRef.current = el.scrollTop;

        const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;

        if (distFromBottom <= 4) {
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
    }, [transcripts, scrollToBottom]);

    // Session switch → always smooth (infrequent event)
    useEffect(() => {
        atBottomRef.current = true;
        scrollToBottom(true);
    }, [sessionId, scrollToBottom]);

    // ── Tool pairing ─────────────────────────────
    const toolPairs = useMemo(
        () => pairToolCalls(transcripts, 0),
        [transcripts],
    );

    const pairsByCallId = useMemo(() => {
        const map = new Map<string, (typeof toolPairs)[number][]>();
        for (const p of toolPairs) {
            const arr = map.get(p.callTranscriptId) || [];
            arr.push(p);
            map.set(p.callTranscriptId, arr);
        }
        return map;
    }, [toolPairs]);

    const pairedResultIds = useMemo(() => {
        const ids = new Set<string>();
        for (const p of toolPairs) {
            if (p.result) ids.add(p.result.id);
        }
        return ids;
    }, [toolPairs]);

    const latestPairKey = toolPairs.length
        ? `${toolPairs[toolPairs.length - 1].callTranscriptId}/${toolPairs[toolPairs.length - 1].callIndex}`
        : null;

    // ── Click-to-focus (rainbow glow) ───────────
    const [focusedId, setFocusedId] = useState<string | null>(null);

    // ── Commit checkout ──────────────────────────
    const [checkingOut, setCheckingOut] = useState<string | null>(null);
    const [prefillContent, setPrefillContent] = useState("");
    // Sync transcript content to commit graph messages
    useEffect(() => {
        for (const t of transcripts) {
            if (!t.commitSha || t.kind !== "user_question") continue;
            const content = String(
                (t.message as Record<string, unknown>).content || "",
            );
            if (!content) continue;
            handleUpdateMessage(t.commitSha, content);
        }
    }, [transcripts]);

    // ── Send handler ─────────────────────────────

    const handleSend = useCallback(
        async (question: string) => {
            if (running && !interrupting) {
                await handleInterrupt();
            }
            handleRun(question);
        },
        [running, interrupting, handleInterrupt, handleRun],
    );

    // ── Unified truncate ──────────────────────────
    // Mirrors backend POST /checkout: orthogonal commit_sha, truncate_tid, keep_tid.

    interface TruncateOpts {
        commitSha?: string;
        removeSha?: string;
        truncateTid: string;
        keepTid: boolean;
        sendContent?: string;
    }


    /**
     * Find the next user_question transcript after tid.
     * Returns its id, or empty string if none (nothing to truncate).
     */
    const nextUserQId = (tid: string): string => {
        const idx = transcripts.findIndex((x) => x.id === tid);
        if (idx < 0) return "";
        for (let i = idx + 1; i < transcripts.length; i++) {
            if (transcripts[i].kind === "user_question") return transcripts[i].id;
        }
        return "";
    };

    const applyTruncate = useCallback(
        async (opts: TruncateOpts) => {
            if (!sessionId) return;
            if (running && !interrupting) {
                await handleInterrupt();
            }
            resetRunning();
            if (opts.commitSha) setCheckingOut(opts.commitSha);

            try {
                await fetch(
                    `/api/session/${sessionId}/checkout`,
                    {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            commit_sha: opts.commitSha || undefined,
                            truncate_tid: opts.truncateTid,
                            keep_tid: opts.keepTid,
                        }),
                    },
                );
            } catch {}

            truncateTranscripts(opts.truncateTid, opts.keepTid);
            if (opts.removeSha) handleRemoveFrom(opts.removeSha);
            if (opts.sendContent) handleRun(opts.sendContent);

            if (opts.commitSha) setCheckingOut(null);
        },
        [sessionId, running, interrupting, handleInterrupt, resetRunning, truncateTranscripts, handleRemoveFrom, handleRun],
    );

    const handleEditSubmit = useCallback(
        (tid: string, content: string) => {
            const t = transcripts.find((item) => item.id === tid);
            const { parent } = t?.commitSha
                ? getCommitActions(commits, t.commitSha)
                : { parent: null };
            applyTruncate({
                commitSha: parent?.sha,
                removeSha: t?.commitSha,
                truncateTid: tid,
                keepTid: false,
                sendContent: content,
            });
        },
        [transcripts, commits, applyTruncate],
    );

    // ── Deprecated handlers (kept for CommitGraphPanel) ──

    const handleCheckout = useCallback(
        async (checkoutSha: string, truncateTid?: string, removeSha?: string) => {
            applyTruncate({ commitSha: checkoutSha, removeSha, truncateTid: truncateTid || "", keepTid: false });
        },
        [applyTruncate],
    );

    const handleCheckoutKeep = useCallback(
        async (checkoutSha: string, truncateTid?: string, removeSha?: string, keepTid = false) => {
            applyTruncate({ commitSha: checkoutSha, removeSha, truncateTid: truncateTid || "", keepTid });
        },
        [applyTruncate],
    );

    const handleReplay = useCallback(
        async (checkoutSha: string, transcriptId?: string, truncateTid?: string, removeSha?: string) => {
            const t = transcriptId ? transcripts.find((x) => x.id === transcriptId) : undefined;
            const content = t ? String((t.message as Record<string, unknown>).content || "") : "";
            applyTruncate({ commitSha: checkoutSha, removeSha, truncateTid: truncateTid || "", keepTid: false, sendContent: content });
        },
        [transcripts, applyTruncate],
    );

    return (
        <div className="agent-demo">
            <div
                className="agent-scroll"
                ref={scrollRef}
                onScroll={handleScroll}
            >
                <div className="agent-scroll-center">
                    <FocusProvider focusedId={focusedId}>
                        <div
                            className="agent-scroll-inner"
                            onClick={(e) => {
                                const el = (e.target as HTMLElement).closest(
                                    "[data-fid]",
                                );
                                if (el) {
                                    const fid = el.getAttribute("data-fid");
                                    if (fid) setFocusedId(fid);
                                }
                            }}
                        >
                            {transcripts.map((t) => {
                                if (pairedResultIds.has(t.id)) return null;
                                const pairs = pairsByCallId.get(t.id);
                                if (pairs) {
                                    return (
                                        <>
                                            {t.kind === "assistant" && (
                                                <div className="assistant-splitter" />
                                            )}
                                            <span
                                                key={t.id}
                                                data-transcript-id={t.id}
                                            >
                                                <TranscriptCard
                                                    transcript={t}
                                                    hideToolCards
                                                />
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
                                if (t.kind === "user_question") {
                                    const content = String(
                                        (t.message as Record<string, unknown>).content || "",
                                    );
                                    const commitSha = t.commitSha;
                                    const shortSha = commitSha
                                        ? commitSha.slice(0, 7)
                                        : null;
                                    return (
                                        <div
                                            key={t.id}
                                            className="user-bubble-wrapper"
                                            data-transcript-id={t.id}
                                        >
                                            <EditableUserBubble
                                                content={content}
                                                onEditSubmit={(c) =>
                                                    handleEditSubmit(t.id, c)
                                                }
                                            />
                                            {(() => {
                                                    if (commitSha) {
                                                        const { parent, next, tid } = getCommitActions(commits, commitSha);
                                                        const shortSha = commitSha.slice(0, 7);
                                                        // tid may be undefined (transcript_id is __init__);
                                                        // fall back to the transcript's own id for truncation.
                                                        const truncateTid = tid || t.id;
                                                        return (
                                                            <CommitBadge
                                                                shortSha={shortSha}
                                                                locked={locked}
                                                                onRegret={
                                                                    parent
                                                                        ? () => applyTruncate({ commitSha: parent.sha, removeSha: commitSha, truncateTid: truncateTid, keepTid: false })
                                                                        : () => applyTruncate({ truncateTid: t.id, keepTid: false })
                                                                }
                                                                onRestore={() => {
                                                                        const tid = nextUserQId(t.id);
                                                                        applyTruncate({
                                                                            commitSha: commitSha,
                                                                            removeSha: next ? next.sha : undefined,
                                                                            truncateTid: tid,
                                                                            keepTid: false,
                                                                        });
                                                                    }}
                                                                onReplay={
                                                                    parent
                                                                        ? () => applyTruncate({ commitSha: parent.sha, removeSha: commitSha, truncateTid: truncateTid, keepTid: false, sendContent: content })
                                                                        : () => applyTruncate({ truncateTid: t.id, keepTid: false, sendContent: content })
                                                                }
                                                            />
                                                        );
                                                    }
                                                    return (
                                                        <CommitBadge
                                                            shortSha=""
                                                            locked={locked}
                                                            onRegret={() => applyTruncate({ truncateTid: t.id, keepTid: false })}
                                                            onRestore={() => applyTruncate({ truncateTid: nextUserQId(t.id), keepTid: false })}
                                                            onReplay={() => applyTruncate({ truncateTid: t.id, keepTid: false, sendContent: content })}
                                                        />
                                                    );
                                                })()}
                                        </div>
                                    );
                                }
                                return (
                                    <span key={t.id} data-transcript-id={t.id}>
                                        {t.kind === "assistant" && (
                                            <div className="assistant-splitter" />
                                        )}
                                        <TranscriptCard transcript={t} />
                                    </span>
                                );
                            })}

                            <div className="agent-bottom-spacer" />
                        </div>
                    </FocusProvider>
                </div>
            </div>

            <AgentInput
                running={running}
                interrupting={interrupting}
                prefillRef={prefillRef}
                prefillContent={prefillContent}
                onPrefillChange={setPrefillContent}
                onSend={handleSend}
                onInterrupt={handleInterrupt}
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
                onReplay={handleReplay}
                onScrollToTranscript={scrollToTranscript}
            />
        </div>
    );
}
