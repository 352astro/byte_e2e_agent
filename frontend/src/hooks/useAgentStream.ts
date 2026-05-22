import { useState, useRef, useCallback, useEffect } from "react";
import type {
    SSEEvent,
    Step,
    Message,
    SessionCache,
    CacheEntry,
    ToolEvent,
} from "../types";

export const RESULT_PREVIEW_LINES = 12;

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
    steps: Step[];
    answer: string | null;
    messages: Message[];
    handleRun: () => Promise<void>;
    toggleStep: (stepId: number) => void;
    expandResult: (stepId: number, evIdx: number) => void;
}

export default function useAgentStream({
    sessionId,
    pendingNew,
    onSessionCreated,
    cache = {},
}: UseAgentStreamOptions): UseAgentStreamReturn {
    const [question, setQuestion] = useState("");
    const [running, setRunning] = useState(false);
    const [steps, setSteps] = useState<Step[]>([]);
    const [answer, setAnswer] = useState<string | null>(null);
    const [messages, setMessages] = useState<Message[]>([]);
    const [currentSid, setCurrentSid] = useState<string | null>(sessionId);

    const currentStepRef = useRef<number | null>(null);
    const globalStepRef = useRef(0);
    const msgIndexRef = useRef(0);
    const lazyCreatedRef = useRef<string | null>(null);
    const reasoningRef = useRef("");
    const actionRef = useRef("");
    const abortRef = useRef<AbortController | null>(null);
    const activeSidRef = useRef<string | null>(sessionId);
    const streamSidRef = useRef<string | null>(null);

    // ── session switch: save & restore ────────────────

    useEffect(() => {
        // 1. Abort any in-flight stream from a *different* session
        if (abortRef.current && streamSidRef.current !== sessionId) {
            abortRef.current.abort();
            abortRef.current = null;
        }

        // 2. Save current state to cache (only if run completed, not mid-stream)
        if (currentSid && currentSid !== sessionId) {
            cache[currentSid] = {
                steps,
                answer,
                messages,
                _stepCounter: globalStepRef.current,
                _complete: !running,
            };
        }

        // 3. Reset per-session refs
        currentStepRef.current = null;
        reasoningRef.current = "";
        actionRef.current = "";
        activeSidRef.current = sessionId;

        // 4. Restore / fetch new session
        if (sessionId && cache[sessionId]) {
            const saved = cache[sessionId];
            if (saved._complete === false) {
                delete cache[sessionId];
                // fall through to backend fetch below
            } else {
                setSteps(saved.steps || []);
                setAnswer(saved.answer ?? null);
                setMessages(saved.messages || []);
                globalStepRef.current = saved._stepCounter || 0;
                setCurrentSid(sessionId);
                return;
            }
        }
        if (sessionId && sessionId !== lazyCreatedRef.current) {
            // Cache miss — fetch from backend
            fetch(`/api/session/${sessionId}/history`)
                .then((r) => r.json())
                .then((data: { history?: HistoryTurn[] }) => {
                    const history = data.history || [];
                    const msgs: Message[] = [];
                    const stps: Step[] = [];
                    let ans: string | null = null;
                    let stepN = 0;
                    for (const t of history) {
                        if (t.role === "user") {
                            msgs.push({ role: "user", content: t.question });
                        } else {
                            stepN += 1;
                            const events: Step["events"] = [];
                            for (const tc of t.tool_calls || []) {
                                events.push({
                                    type: "tool_call",
                                    tool: tc.name,
                                    params: tc.arguments,
                                });
                                if (tc.result)
                                    events.push({
                                        type: "tool_result",
                                        result: tc.result,
                                    });
                            }
                            stps.push({
                                step: stepN,
                                reasoning: t.reasoning,
                                action: t.content,
                                events,
                                open: false,
                                actionFinal: true,
                                msgIndex: msgs.length - 1,
                            });
                            if (t.finish_answer) ans = t.finish_answer;
                        }
                    }
                    setMessages(msgs);
                    setSteps(stps);
                    setAnswer(ans);
                    globalStepRef.current = stepN;
                    cache[sessionId] = {
                        steps: stps,
                        answer: ans,
                        messages: msgs,
                        _stepCounter: stepN,
                        _complete: true,
                    };
                })
                .catch((err: unknown) => {
                    console.warn("Failed to load session history:", err);
                });
        } else if (sessionId && sessionId === lazyCreatedRef.current) {
            lazyCreatedRef.current = null;
        } else if (!sessionId && pendingNew) {
            setSteps([]);
            setAnswer(null);
            setMessages([]);
            globalStepRef.current = 0;
        }
        setCurrentSid(sessionId);
    }, [sessionId, pendingNew]); // eslint-disable-line react-hooks/exhaustive-deps

    // Save state to cache on change
    useEffect(() => {
        return () => {
            if (currentSid) {
                cache[currentSid] = {
                    steps,
                    answer,
                    messages,
                    _stepCounter: globalStepRef.current,
                    _complete: !running,
                };
            }
        };
    }, [currentSid, steps, answer, messages, running]); // eslint-disable-line

    // Abort stream on unmount only
    useEffect(() => {
        return () => {
            if (abortRef.current) {
                abortRef.current.abort();
                abortRef.current = null;
            }
        };
    }, []);

    // ── helpers ──────────────────────────────────────

    const updateCurrentStep = useCallback((fn: (s: Step) => Step) => {
        setSteps((prev) => {
            const idx = prev.length - 1;
            if (idx < 0) return prev;
            const copy = [...prev];
            copy[idx] = fn(copy[idx]);
            return copy;
        });
    }, []);

    const finalizeStep = useCallback(() => {
        setSteps((prev) => {
            const idx = prev.length - 1;
            if (idx < 0) return prev;
            const copy = [...prev];
            copy[idx] = { ...copy[idx], open: false, actionFinal: true };
            return copy;
        });
    }, []);

    // ── event dispatcher ─────────────────────────────

    const dispatch = useCallback(
        (event: SSEEvent) => {
            // ── session guard ──
            if (
                streamSidRef.current &&
                streamSidRef.current !== activeSidRef.current
            )
                return;

            switch (event.type) {
                case "step_start": {
                    if (currentStepRef.current !== null) finalizeStep();
                    globalStepRef.current += 1;
                    currentStepRef.current = globalStepRef.current;
                    reasoningRef.current = "";
                    actionRef.current = "";
                    setSteps((prev) => [
                        ...prev,
                        {
                            step: globalStepRef.current,
                            msgIndex: msgIndexRef.current,
                            reasoning: "",
                            action: "",
                            events: [],
                            open: true,
                        },
                    ]);
                    break;
                }

                case "reasoning_token":
                    reasoningRef.current += event.token;
                    updateCurrentStep((s) => ({
                        ...s,
                        reasoning: reasoningRef.current,
                    }));
                    break;

                case "thought_token":
                    actionRef.current += event.token;
                    updateCurrentStep((s) => ({
                        ...s,
                        action: actionRef.current,
                    }));
                    break;

                case "thought_end":
                    updateCurrentStep((s) => ({ ...s, actionFinal: true }));
                    break;

                case "tool_call_stream":
                    updateCurrentStep((s) => {
                        const events = [...s.events];
                        const last = events[events.length - 1];
                        if (last && last.type === "tool_stream") {
                            events[events.length - 1] = {
                                ...last,
                                name: event.name || last.name,
                                argsLen: event.args_len,
                            };
                        } else {
                            events.push({
                                type: "tool_stream",
                                name: event.name || "",
                                argsLen: event.args_len,
                            });
                        }
                        return { ...s, events };
                    });
                    break;

                case "tool_call":
                case "tool_result":
                case "plan_rewrite":
                case "plan_advance":
                case "subtask_start":
                case "subtask_end":
                    updateCurrentStep((s) => ({
                        ...s,
                        events: [...s.events, event],
                    }));
                    break;

                case "terminal_chunk":
                    updateCurrentStep((s) => {
                        const events = [...s.events];
                        const last = events[events.length - 1];
                        if (last && last.type === "terminal_stream") {
                            events[events.length - 1] = {
                                ...last,
                                output: last.output + event.chunk,
                            };
                        } else {
                            events.push({
                                type: "terminal_stream",
                                output: event.chunk,
                            });
                        }
                        return { ...s, events };
                    });
                    break;

                case "finish":
                    setAnswer(event.answer);
                    break;

                case "error":
                    updateCurrentStep((s) => ({
                        ...s,
                        events: [...s.events, event],
                    }));
                    break;
            }
        },
        [updateCurrentStep, finalizeStep],
    );

    // ── run ──────────────────────────────────────────

    const handleRun = useCallback(async () => {
        const q = question.trim();
        if (!q || running) return;

        setRunning(true);
        setAnswer(null);
        currentStepRef.current = null;
        reasoningRef.current = "";
        actionRef.current = "";

        const msgIdx = messages.length;
        msgIndexRef.current = msgIdx;
        setMessages((prev) => [...prev, { role: "user", content: q }]);
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
                activeSidRef.current = sid;
                lazyCreatedRef.current = sid;
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

        // Claim ownership of this stream
        streamSidRef.current = sid;
        const controller = new AbortController();
        abortRef.current = controller;

        try {
            const res = await fetch(`/api/session/${sid}/chat`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question: q, max_steps: 50 }),
                signal: controller.signal,
            });

            if (!res.ok) {
                throw new Error(
                    res.status === 404
                        ? "Session not found. It may have been deleted."
                        : `Server returned ${res.status}`,
                );
            }

            const reader = res.body!.getReader();
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
                        const event = JSON.parse(line.slice(6)) as SSEEvent;
                        dispatch(event);
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
            streamSidRef.current = null;
            setRunning(false);
        }
    }, [
        question,
        running,
        dispatch,
        currentSid,
        pendingNew,
        onSessionCreated,
        messages,
    ]);

    // ── step UI actions ──────────────────────────────

    const toggleStep = useCallback((stepId: number) => {
        setSteps((prev) => {
            const copy = [...prev];
            const idx = copy.findIndex((s) => s.step === stepId);
            if (idx < 0) return prev;
            copy[idx] = { ...copy[idx], open: !copy[idx].open };
            return copy;
        });
    }, []);

    const expandResult = useCallback((stepId: number, evIdx: number) => {
        setSteps((prev) => {
            const copy = [...prev];
            const idx = copy.findIndex((s) => s.step === stepId);
            if (idx < 0) return prev;
            const evts = [...copy[idx].events];
            evts[evIdx] = { ...evts[evIdx], expanded: true } as ToolEvent;
            copy[idx] = { ...copy[idx], events: evts };
            return copy;
        });
    }, []);

    return {
        question,
        setQuestion,
        running,
        steps,
        answer,
        messages,
        handleRun,
        toggleStep,
        expandResult,
    };
}

// ── History types (from backend) ─────────────────────

interface HistoryToolCall {
    name: string;
    arguments: Record<string, unknown>;
    result?: string;
}

interface HistoryTurn {
    role: "user" | "assistant";
    question: string;
    reasoning: string;
    content: string;
    tool_calls: HistoryToolCall[];
    finish_answer: string | null;
}
