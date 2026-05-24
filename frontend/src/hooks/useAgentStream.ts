import { useState, useRef, useCallback, useEffect } from "react";
import type {
    DisplayTranscript,
    SessionCache,
    StreamEvent,
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
    const [currentSid, setCurrentSid] = useState<string | null>(sessionId);

    const abortRef = useRef<AbortController | null>(null);
    const lazyCreatedRef = useRef<string | null>(null);
    const lastIdRef = useRef<string | null>(null);
    const fetchForRef = useRef<string | null>(null);
    // Set before onSessionCreated, cleared when SSE ends — prevents
    // the effect from doing a recover fetch while SSE is populating.
    const streamingSidRef = useRef<string | null>(null);

    // ── session switch: save & restore ────────────────

    useEffect(() => {
        // Abort previous stream
        if (abortRef.current) {
            abortRef.current.abort();
            abortRef.current = null;
        }

        // Save current state ONLY when switching to a different session
        if (currentSid && currentSid !== sessionId) {
            cache[currentSid] = {
                transcripts,
                answer,
                _complete: !running,
            };
        }

        // ── No session selected / New Session (blank slate) ──
        if (!sessionId) {
            setTranscripts([]);
            setAnswer(null);
            lastIdRef.current = null;
            setCurrentSid(null);
            return;
        }

        // ── Currently streaming — don't fetch, SSE is populating ──
        if (sessionId === streamingSidRef.current) {
            setCurrentSid(sessionId);
            return;
        }

        // ── Cache hit (completed session) ──────────────
        const cached = cache[sessionId];
        if (cached && cached._complete) {
            setTranscripts(cached.transcripts || []);
            setAnswer(cached.answer ?? null);
            lastIdRef.current = cached.transcripts?.length
                ? cached.transcripts[cached.transcripts.length - 1].id
                : null;
            setCurrentSid(sessionId);
            return;
        }

        // ── Lazy-created, SSE about to start ──────────
        if (sessionId === lazyCreatedRef.current) {
            lazyCreatedRef.current = null;
            streamingSidRef.current = sessionId;
            setCurrentSid(sessionId);
            return;
        }

        // ── Cache miss — fetch from server ─────────────
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
                        pendingChunks: "",
                        isFlushed: true,
                    }),
                );

                setTranscripts(items);

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
                    const accumulated =
                        (existing?.pendingChunks ?? "") + ev.text;
                    const t: DisplayTranscript = {
                        id: ev.transcript_id,
                        kind: existing?.kind ?? "",
                        message: existing?.message ?? { content: "" },
                        pendingChunks: accumulated,
                        isFlushed: false,
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
                upsertTranscript({
                    id: ev.transcript_id,
                    kind: ev.kind,
                    message: msg,
                    pendingChunks: "",
                    isFlushed: true,
                });
                lastIdRef.current = ev.transcript_id;
            }
        },
        [upsertTranscript],
    );

    // ── run ──────────────────────────────────────────

    const handleRun = useCallback(async () => {
        const q = question.trim();
        if (!q || running) return;

        setRunning(true);
        setAnswer(null);
        setQuestion("");

        // Lazy-create session
        let sid = currentSid;
        if (!sid && pendingNew) {
            try {
                const res = await fetch("/api/session", { method: "POST" });
                if (!res.ok) throw new Error(`Server returned ${res.status}`);
                const data: { session_id: string } = await res.json();
                sid = data.session_id;
                setCurrentSid(sid);
                lazyCreatedRef.current = sid;
                streamingSidRef.current = sid; // block recover fetch
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

        // User question is sent by backend SSE — no manual insert needed

        // POST /chat returns SSE directly (subscribe-before-start)
        const controller = new AbortController();
        abortRef.current = controller;
        try {
            const streamRes = await fetch(`/api/session/${sid}/chat`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question: q, max_steps: 50 }),
                signal: controller.signal,
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
            streamingSidRef.current = null; // allow recover fetch again
            setRunning(false);
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
        transcripts,
        answer,
        handleRun,
    };
}
