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
}

interface UseAgentStreamReturn {
    question: string;
    setQuestion: (q: string) => void;
    running: boolean;
    transcripts: DisplayTranscript[];
    answer: string | null;
    handleRun: () => Promise<void>;
    prefillRef: React.MutableRefObject<string>;
    reloadTranscripts: () => void;
    handleInterrupt: () => Promise<void>;
    interrupting: boolean;
}

export default function useAgentStream({
    sessionId,
    pendingNew,
    onSessionCreated,
    cache = {},
}: UseAgentStreamOptions): UseAgentStreamReturn {
    const [question, setQuestion] = useState("");
    const [running, setRunning] = useState(false);
    const [transcripts, setTranscripts] = useState<DisplayTranscript[]>([]);
    const [answer, setAnswer] = useState<string | null>(null);
    const [interrupting, setInterrupting] = useState(false);
    const [currentSid, setCurrentSid] = useState<string | null>(sessionId);

    const abortRef = useRef<AbortController | null>(null);
    const lazyCreatedRef = useRef<string | null>(null);
    const lastIdRef = useRef<string | null>(null);
    const fetchForRef = useRef<string | null>(null);
    const streamingSidRef = useRef<string | null>(null);
    const prefillRef = useRef<string>("");

    // ── session switch: save & restore ────────────────

    useEffect(() => {
        if (currentSid && currentSid !== sessionId) {
            cache[currentSid] = {
                transcripts,
                answer,
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
            setAnswer(null);
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
            setAnswer(cached.answer ?? null);
            lastIdRef.current = cached.transcripts?.length
                ? cached.transcripts[cached.transcripts.length - 1].id
                : null;
            setCurrentSid(sessionId);
            // Verify running state with backend (cache may be stale)
            fetch(`/api/session/${sessionId}/recover`)
                .then((r) => r.json())
                .then((data: RecoverResponse) => {
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
            setAnswer(null);
        }
        setCurrentSid(sessionId);

        const fetchFor = sessionId;
        fetchForRef.current = fetchFor;

        fetch(`/api/session/${sessionId}/recover`)
            .then((r) => {
                if (!r.ok) throw new Error(`Server returned ${r.status}`);
                return r.json();
            })
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
                const ans = lastAssistant
                    ? String(lastAssistant.message.content || "")
                    : null;
                setAnswer(ans);

                lastIdRef.current = items.length
                    ? items[items.length - 1].id
                    : null;

                cache[sessionId] = {
                    transcripts: items,
                    answer: ans,
                    _complete: !data.running,
                };
            })
            .catch((err) => {
                console.error("Failed to recover session", fetchFor, err);
                if (fetchForRef.current === fetchFor) {
                    setAnswer(
                        `Failed to load session: ${err instanceof Error ? err.message : err}`,
                    );
                }
            });
    }, [sessionId, pendingNew]); // eslint-disable-line react-hooks/exhaustive-deps

    // ── reload ─────────────────────────────────────

    const reloadTranscripts = useCallback(() => {
        if (!sessionId) return;
        const fetchFor = sessionId;
        fetchForRef.current = fetchFor;
        fetch(`/api/session/${sessionId}/recover`)
            .then((r) => r.json())
            .then((data: RecoverResponse) => {
                if (fetchForRef.current !== fetchFor) return;
                const items: DisplayTranscript[] = (data.transcripts || []).map(
                    (t: Transcript) => ({
                        id: t.id, kind: t.kind, message: t.message,
                        subStreams: [], activeSubStream: null, isFlushed: true,
                        commitSha: t.commit_sha,
                    }),
                );
                setTranscripts(items);
                if (data.running) setRunning(true);
                setInterrupting(false);
                const lastAssistant = [...items].reverse().find((t: any) => t.kind === "assistant" && t.message.content);
                setAnswer(lastAssistant ? String(lastAssistant.message.content || "") : null);
                lastIdRef.current = items.length ? items[items.length - 1].id : null;
                cache[sessionId] = { transcripts: items, answer: lastAssistant ? String(lastAssistant.message.content || "") : null, _complete: !data.running };
            })
            .catch((err) => { console.error("Failed to reload session", fetchFor, err); });
    }, [sessionId, cache]);

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
                        kind: existing?.kind ?? (ev.kind === "tool_result" ? "tool_result" : "assistant"),
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
                if (
                    ev.kind === "assistant" &&
                    msg.content &&
                    !(msg as Record<string, unknown>).tool_calls
                ) {
                    setAnswer(String(msg.content));
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
                    commitSha: (ev as Record<string, unknown>).commit_sha as string | undefined,
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
        setAnswer(null);
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
                setAnswer(
                    `Failed to create session: ${err instanceof Error ? err.message : err}`,
                );
                setRunning(false);
                return;
            }
        }
        if (!sid) {
            setAnswer("No session selected.");
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
                signal: AbortSignal.any([controller.signal, AbortSignal.timeout(300_000)]),
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
            setAnswer(
                `Connection error: ${err instanceof Error ? err.message : err}`,
            );
        } finally {
            if (abortRef.current === controller) abortRef.current = null;
            streamingSidRef.current = null;
            lazyCreatedRef.current = null;
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
        answer,
        handleRun,
        prefillRef,
        reloadTranscripts,
        handleInterrupt,
    };
}
