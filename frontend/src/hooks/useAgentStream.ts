import { useState, useRef, useCallback, useEffect } from "react";
import type {
    DisplayTranscript,
    SessionCache,
    StreamEvent,
    SubStream,
    Transcript,
    RecoverResponse,
} from "../types";

interface UseAgentStreamOptions {
    sessionId: string | null;
    pendingNew: boolean;
    onSessionCreated?: (sid: string) => void;
    cache?: SessionCache;
    scrollContainerRef?: React.RefObject<HTMLDivElement | null>;
    onCommit?: (targetTid: string, commitSha: string) => void;
}

interface UseAgentStreamReturn {
    question: string;
    setQuestion: (q: string) => void;
    running: boolean;
    transcripts: DisplayTranscript[];
    handleRun: () => Promise<void>;
    prefillRef: React.MutableRefObject<string>;
    reloadTranscripts: () => void;
    truncateTranscripts: (truncateTid: string) => void;
    handleInterrupt: () => Promise<void>;
    interrupting: boolean;
    scrollToTranscript: (id: string) => void;
}

export default function useAgentStream({
    sessionId,
    pendingNew,
    onSessionCreated,
    cache = {},
    scrollContainerRef,
    onCommit,
}: UseAgentStreamOptions): UseAgentStreamReturn {
    const [question, setQuestion] = useState("");
    const [running, setRunning] = useState(false);
    const [transcripts, setTranscripts] = useState<DisplayTranscript[]>([]);
    const [interrupting, setInterrupting] = useState(false);
    const [currentSid, setCurrentSid] = useState<string | null>(sessionId);

    const abortRef = useRef<AbortController | null>(null);
    const lazyCreatedRef = useRef<string | null>(null);
    const lastIdRef = useRef<string | null>(null);
    const fetchForRef = useRef<string | null>(null);
    const streamingSidRef = useRef<string | null>(null);
    const prefillRef = useRef<string>("");

    // ── reload ─────────────────────────────────────

    const reloadTranscripts = useCallback((): Promise<void> => {
        if (!sessionId) return Promise.resolve();
        const fetchFor = sessionId;
        fetchForRef.current = fetchFor;
        return fetch(`/api/session/${sessionId}/recover`)
            .then((r) => r.json())
            .then((data: RecoverResponse) => {
                if (fetchForRef.current !== fetchFor) return;
                const items: DisplayTranscript[] = (data.transcripts || []).map(
                    (t: Transcript) => ({
                        id: t.id,
                        kind: t.kind,
                        message: t.message,
                        subStreams: [],
                        activeSubStream: null,
                        isFlushed: true,
                        commitSha: t.commit_sha,
                    }),
                );
                setTranscripts(items);
                if (data.running) setRunning(true);
                setInterrupting(false);
                const lastAssistant = [...items]
                    .reverse()
                    .find((t) => t.kind === "assistant" && t.message.content);
                lastIdRef.current = items.length
                    ? items[items.length - 1].id
                    : null;
                cache[sessionId] = {
                    transcripts: items,
                    _complete: !data.running,
                };
            });
    }, [sessionId, cache]);


    const truncateTranscripts = useCallback((truncateTid: string) => {
        if (!sessionId || !truncateTid) return;
        setTranscripts((prev) => {
            const idx = prev.findIndex((t) => t.id === truncateTid);
            if (idx < 0) return prev;
            const kept = prev.slice(0, idx);
            const lastAssistant = [...kept]
                .reverse()
                .find((t) => t.kind === "assistant" && t.message.content);
            const ans = lastAssistant
                ? String(lastAssistant.message.content || "")
                : null;
            setRunning(false);
            setInterrupting(false);
            lastIdRef.current = kept.length
                ? kept[kept.length - 1].id
                : null;
            cache[sessionId] = {
                transcripts: kept,
                _complete: true,
            };
            return kept;
        });
    }, [sessionId, cache]);

    // ── session switch: save & restore ────────────────

    useEffect(() => {
        if (currentSid && currentSid !== sessionId) {
            cache[currentSid] = {
                transcripts,
                _complete: !running,
            };
        }

        if (!sessionId) {
            // If a stream is being set up (lazy session creation in flight),
            // do NOT clear currentSid — the next render will have the real sessionId.
            if (streamingSidRef.current) {
                return;
            }
            if (abortRef.current) {
                abortRef.current.abort();
                abortRef.current = null;
            }
            setTranscripts([]);
            setInterrupting(false);
            lastIdRef.current = null;
            setCurrentSid(null);
            return;
        }

        if (sessionId === streamingSidRef.current) {
            setCurrentSid(sessionId);
            return;
        }

        if (abortRef.current) {
            abortRef.current.abort();
            abortRef.current = null;
        }

        const cached = cache[sessionId];
        if (cached && cached._complete) {
            setTranscripts(cached.transcripts || []);
            lastIdRef.current = cached.transcripts?.length
                ? cached.transcripts[cached.transcripts.length - 1].id
                : null;
            setCurrentSid(sessionId);
            // Verify running state with backend (cache may be stale)
            fetch(`/api/session/${sessionId}/status`)
                .then((r) => r.json())
                .then((data: { running: boolean }) => {
                    if (data.running) {
                        setRunning(true);
                        cache[sessionId]._complete = false;
                    }
                })
                .catch(() => {});
            return;
        }

        if (sessionId === lazyCreatedRef.current) {
            lazyCreatedRef.current = null;
            streamingSidRef.current = sessionId;
            setCurrentSid(sessionId);
            return;
        }

        if (currentSid !== sessionId) {
            setTranscripts([]);
        }
        setCurrentSid(sessionId);

        reloadTranscripts().catch((err) => {
            console.error("Failed to recover session", sessionId, err);
        });
    }, [sessionId, pendingNew]); // eslint-disable-line react-hooks/exhaustive-deps

    // ── scroll to transcript ──────────────────────

    const scrollToTranscript = useCallback(
        (id: string) => {
            const el = scrollContainerRef?.current;
            if (!el) return;
            const target = el.querySelector(`[data-transcript-id="${id}"]`);
            if (target) {
                target.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        },
        [scrollContainerRef],
    );

    // ── interrupt ─────────────────────────────────

    const handleInterrupt = useCallback(async () => {
        if (interrupting) return;
        setInterrupting(true);
        try {
            await fetch("/api/interrupt", { method: "POST" });
        } catch {}
        setInterrupting(false);
        setRunning(false);
    }, [interrupting]);

    // ── helpers ──────────────────────────────────────

    const upsertTranscript = useCallback((t: DisplayTranscript) => {
        setTranscripts((prev) => {
            const idx = prev.findIndex((item) => item.id === t.id);
            if (idx >= 0) {
                const copy = [...prev];
                copy[idx] = t;
                return copy;
            }
            return [...prev, t];
        });
    }, []);

    // ── stream event dispatch ────────────────────────

    const dispatchStreamEvent = useCallback(
        (ev: StreamEvent) => {
            if (ev.event === "chunk") {
                setTranscripts((prev) => {
                    const idx = prev.findIndex(
                        (item) => item.id === ev.transcript_id,
                    );
                    const existing = idx >= 0 ? prev[idx] : null;
                    let subStreams = existing?.subStreams ?? [];
                    let active = existing?.activeSubStream ?? null;

                    if (
                        active &&
                        (active.id !== ev.id || active.kind !== ev.kind)
                    ) {
                        subStreams = [...subStreams, active];
                        active = null;
                    }

                    if (
                        active &&
                        active.id === ev.id &&
                        active.kind === ev.kind
                    ) {
                        active = {
                            ...active,
                            text: active.text + ev.text,
                        };
                    } else {
                        active = {
                            id: ev.id,
                            kind: ev.kind,
                            text: ev.text,
                        };
                    }

                    const t: DisplayTranscript = {
                        id: ev.transcript_id,
                        kind:
                            existing?.kind ??
                            (ev.kind === "tool_result"
                                ? "tool_result"
                                : "assistant"),
                        message: existing?.message ?? {},
                        subStreams,
                        activeSubStream: active,
                        isFlushed: false,
                        commitSha: existing?.commitSha,
                    };
                    if (idx >= 0) {
                        const copy = [...prev];
                        copy[idx] = t;
                        return copy;
                    }
                    return [...prev, t];
                });
            } else if (ev.event === "flush") {
                const msg = ev.message || {};

                // commit_attachment: update transcript + notify graph directly
                if (ev.kind === "commit_attachment") {
                    const targetTid = (msg as Record<string, unknown>)
                        .target_tid as string | undefined;
                    const commitSha = (msg as Record<string, unknown>)
                        .commit_sha as string | undefined;
                    if (targetTid && commitSha) {
                        setTranscripts((prev) =>
                            prev.map((item) =>
                                item.id === targetTid
                                    ? { ...item, commitSha }
                                    : item,
                            ),
                        );
                        onCommit?.(targetTid, commitSha);
                    }
                    return;
                }

                if (
                    ev.kind === "assistant" &&
                    msg.content &&
                    !(msg as Record<string, unknown>).tool_calls
                ) {
                }

                // 后端 StreamChannel 内部 Transcript 已等效拼接，
                // flush 直接携带完整 sub_streams，无需前端重建
                const ss: SubStream[] = (ev.sub_streams || []).map((s) => ({
                    id: s.id,
                    kind: s.kind,
                    text: s.text,
                }));

                upsertTranscript({
                    id: ev.transcript_id,
                    kind: ev.kind,
                    message: msg,
                    subStreams: ss,
                    activeSubStream: null,
                    isFlushed: true,
                    commitSha: (ev as Record<string, unknown>).commit_sha as
                        | string
                        | undefined,
                });
                lastIdRef.current = ev.transcript_id;
            }
        },
        [upsertTranscript],
    );

    // ── run ──────────────────────────────────────────

    const handleRun = useCallback(async () => {
        const prefill = prefillRef.current.trim();
        if (prefill) {
            prefillRef.current = "";
        }
        const q = (prefill ? prefill + "\n" + question : question).trim();
        if (!q || running) return;

        setRunning(true);
        setInterrupting(false);
        setQuestion("");

        let sid = currentSid;
        if (!sid && pendingNew) {
            try {
                const res = await fetch("/api/session", { method: "POST" });
                if (!res.ok) throw new Error(`Server returned ${res.status}`);
                const data: { session_id: string } = await res.json();
                sid = data.session_id;
                setCurrentSid(sid);
                lazyCreatedRef.current = sid;
                streamingSidRef.current = sid;
                if (onSessionCreated) onSessionCreated(sid);
            } catch (err) {
                setRunning(false);
                return;
            }
        }
        if (!sid) {
            setRunning(false);
            return;
        }

        streamingSidRef.current = sid;

        const controller = new AbortController();
        abortRef.current = controller;
        try {
            const streamRes = await fetch(`/api/session/${sid}/chat`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question: q, max_steps: 50 }),
                signal: AbortSignal.any([
                    controller.signal,
                    AbortSignal.timeout(300_000),
                ]),
            });
            if (!streamRes.ok) {
                throw new Error(
                    streamRes.status === 409
                        ? "Session is already running"
                        : `Server returned ${streamRes.status}`,
                );
            }

            const reader = streamRes.body!.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const parts = buffer.split("\n\n");
                buffer = parts.pop()!;

                for (const part of parts) {
                    const line = part.trim();
                    if (!line.startsWith("data: ")) continue;
                    try {
                        const event = JSON.parse(line.slice(6)) as StreamEvent;
                        dispatchStreamEvent(event);
                    } catch {
                        // ignore malformed JSON
                    }
                }
            }
        } catch (err) {
            if (err instanceof DOMException && err.name === "AbortError")
                return;
        } finally {
            if (abortRef.current === controller) abortRef.current = null;
            streamingSidRef.current = null;
            lazyCreatedRef.current = null;
            // 向后端确认 session 是否仍在运行，避免 running 状态永不停止
            if (sid) {
                try {
                    const res = await fetch(`/api/session/${sid}/status`);
                    if (res.ok) {
                        const data = await res.json();
                        if (!data.running) {
                            setRunning(false);
                        }
                    } else {
                        setRunning(false);
                    }
                } catch {
                    setRunning(false);
                }
            } else {
                setRunning(false);
            }
        }
    }, [
        question,
        running,
        dispatchStreamEvent,
        upsertTranscript,
        currentSid,
        pendingNew,
        onSessionCreated,
    ]);

    return {
        question,
        setQuestion,
        running,
        interrupting,
        transcripts,
        handleRun,
        prefillRef,
        reloadTranscripts,
        truncateTranscripts,
        handleInterrupt,
        scrollToTranscript,
    };
}
