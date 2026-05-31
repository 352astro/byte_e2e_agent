import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import type { Message, StreamEvent, RecoverData } from "../types";

// ── types ────────────────────────────────────────────

interface UseAgentStreamOptions {
  sessionId: string | null;
  onSessionCreated?: (sid: string) => void;
  scrollContainerRef?: React.RefObject<HTMLDivElement | null>;
}

const BUSY_MESSAGE = "系统正在繁忙，请稍后再试";

export interface UseAgentStreamReturn {
  // ── 只读状态 ──
  running: boolean;
  interrupting: boolean;
  messages: Message[];
  activeMessage: Message | null;

  // ── 命令（异步）──
  send: (question: string) => Promise<void>;
  interrupt: () => Promise<void>;
  reloadMessages: () => Promise<void>;

  // ── 命令（同步）──
  truncateMessages: (truncateTid: string, keep?: boolean) => void;
  resetRunning: () => void;

  // ── 工具 ──
  createSession: () => Promise<string>;
  prefillRef: React.MutableRefObject<string>;
  scrollToMessage: (id: string) => void;
  runError: string | null;
  clearRunError: () => void;
}

// ── helpers ───────────────────────────────────────────

function emptyMessage(id: string, turnId: string, role: string): Message {
  return {
    id,
    turn_id: turnId,
    role: role || "assistant",
    status: "streaming",
    content: "",
    reasoning: "",
    tool_calls: [],
    tool_result: "",
    tool_call_id: "",
    tool_name: "",
    error: "",
  } as Message;
}

function emptyTC(): Record<string, unknown> {
  return { id: "", type: "function", function: { name: "", arguments: "" } };
}

// ── hook ──────────────────────────────────────────────

export default function useAgentStream({
  sessionId,
  onSessionCreated,
  scrollContainerRef,
}: UseAgentStreamOptions): UseAgentStreamReturn {
  // ═══════════════════════════════════════════════════
  //  State
  // ═══════════════════════════════════════════════════

  const [running, _setRunning] = useState(false);
  const [completed, setCompleted] = useState<Message[]>([]);
  const [active, setActive] = useState<Message | null>(null);
  const [interrupting, setInterrupting] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  // ═══════════════════════════════════════════════════
  //  Refs (mutable, no re-render on change)
  // ═══════════════════════════════════════════════════

  const genRef = useRef(0);
  const opGuardRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const runningRef = useRef(false);
  const prefillRef = useRef("");
  const streamSidRef = useRef<string | null>(null);
  const chatStreamActiveRef = useRef(false);
  const lastIdRef = useRef<string | null>(null);
  const prevSidRef = useRef<string | null>(sessionId);
  const completedIdsRef = useRef<Set<string>>(new Set());

  // ═══════════════════════════════════════════════════
  //  Derived
  // ═══════════════════════════════════════════════════

  const messages = useMemo(
    () => (active ? [...completed, active] : completed),
    [completed, active],
  );

  // ═══════════════════════════════════════════════════
  //  Internal helpers
  // ═══════════════════════════════════════════════════

  const setRunning = (v: boolean) => {
    runningRef.current = v;
    _setRunning(v);
  };

  const bumpGen = () => {
    genRef.current += 1;
    return genRef.current;
  };

  const appendCompleted = useCallback((msg: Message) => {
    setCompleted((prev) => {
      if (prev.some((m) => m.id === msg.id)) return prev;
      completedIdsRef.current.add(msg.id);
      return [...prev, msg];
    });
  }, []);

  useEffect(() => {
    completedIdsRef.current = new Set(completed.map((m) => m.id));
  }, [completed]);

  const clearRunError = useCallback(() => {
    setRunError(null);
  }, []);

  useEffect(() => {
    if (!runError) return;
    const timer = window.setTimeout(() => setRunError(null), 5000);
    return () => window.clearTimeout(timer);
  }, [runError]);

  // ═══════════════════════════════════════════════════
  //  createSession
  // ═══════════════════════════════════════════════════

  const createSession = useCallback(async (): Promise<string> => {
    const res = await fetch("/api/session", { method: "POST" });
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const data = await res.json();
    return data.session_id as string;
  }, []);

  // ═══════════════════════════════════════════════════
  //  reloadMessagesInternal (private, with gen gate)
  // ═══════════════════════════════════════════════════

  const reloadMessagesInternal = useCallback(
    async (sid: string, gen: number) => {
      try {
        const res = await fetch(`/api/session/${sid}/recover`);
        if (!res.ok) return;
        const data: RecoverData = await res.json();
        if (genRef.current !== gen) return; // gen gate
        const msgs: Message[] = data.messages || [];
        completedIdsRef.current = new Set(msgs.map((m) => m.id));
        setCompleted(msgs);
        setActive(null);
        lastIdRef.current = msgs.length ? msgs[msgs.length - 1].id : null;
        if (data.running) {
          setRunning(true);
          streamSidRef.current = sid;
        }
      } catch {
        // network error, ignore
      }
    },
    [],
  );

  // ═══════════════════════════════════════════════════
  //  reloadMessages (public)
  // ═══════════════════════════════════════════════════

  const reloadMessages = useCallback(async (): Promise<void> => {
    if (!sessionId) return;
    const gen = genRef.current;
    await reloadMessagesInternal(sessionId, gen);
  }, [sessionId, reloadMessagesInternal]);

  // ═══════════════════════════════════════════════════
  //  truncateMessages (sync, local only)
  // ═══════════════════════════════════════════════════

  const truncateMessages = useCallback(
    (truncateTid: string, keep = false) => {
      if (!sessionId || !truncateTid) return;
      setCompleted((prev) => {
        const idx = prev.findIndex((m) => m.id === truncateTid);
        if (idx < 0) return prev;
        const cutoff = keep ? idx + 1 : idx;
        if (cutoff >= prev.length) return prev;
        const kept = prev.slice(0, cutoff);
        completedIdsRef.current = new Set(kept.map((m) => m.id));
        lastIdRef.current = kept.length ? kept[kept.length - 1].id : null;
        return kept;
      });
      setActive(null);
    },
    [sessionId],
  );

  // ═══════════════════════════════════════════════════
  //  dispatchStreamEvent (with gen gate)
  // ═══════════════════════════════════════════════════

  const dispatchStreamEvent = useCallback(
    (ev: StreamEvent, gen: number) => {
      switch (ev.kind) {
        case "message_start": {
          if (genRef.current !== gen) return;
          setActive((prev) => {
            if (completedIdsRef.current.has(ev.message_id)) return prev;
            if (prev?.id === ev.message_id) return prev;
            if (prev) appendCompleted(prev);
            return emptyMessage(ev.message_id, ev.turn_id, ev.role);
          });
          break;
        }

        case "chunk_delta": {
          if (genRef.current !== gen) return;
          const { field, delta, tool_index, sub_field } = ev;
          setActive((prev) => {
            if (!prev || prev.id !== ev.message_id) return prev;

            if (field === "tool_calls") {
              const idx = tool_index >= 0 ? tool_index : 0;
              const tcs = [...(prev.tool_calls || [])];
              while (tcs.length <= idx) tcs.push(emptyTC() as any);
              const srcFn = tcs[idx].function || { name: "", arguments: "" };
              const fn: { name: string; arguments: string } = {
                name: srcFn.name || "",
                arguments: srcFn.arguments || "",
              };
              if (sub_field === "name") {
                fn.name += delta;
              } else if (sub_field === "args") {
                fn.arguments += delta;
              }
              tcs[idx] = { ...tcs[idx], function: fn };
              return { ...prev, tool_calls: tcs };
            }

            return { ...prev, [field]: (prev as any)[field] + delta };
          });
          break;
        }

        case "chunk_complete": {
          if (genRef.current !== gen) return;
          const { field, full_content } = ev;
          if (field === "tool_calls") break;
          setActive((prev) => {
            if (!prev || prev.id !== ev.message_id) return prev;
            return { ...prev, [field]: full_content };
          });
          break;
        }

        case "message_finish": {
          if (genRef.current !== gen) return;
          setActive((prev) => {
            if (!prev || prev.id !== ev.message_id) return prev;
            const done = { ...prev, status: "complete" as const };
            appendCompleted(done);
            lastIdRef.current = ev.message_id;
            return null;
          });
          break;
        }

        case "turn_complete":
        case "interrupted": {
          if (genRef.current !== gen) return;
          setActive((prev) => {
            if (prev) appendCompleted({ ...prev, status: "complete" as const });
            return null;
          });
          setRunning(false);
          break;
        }
      }
    },
    [appendCompleted],
  );

  // ═══════════════════════════════════════════════════
  //  readSSEStream (shared by send + auto-reconnect)
  // ═══════════════════════════════════════════════════

  const readSSEStream = useCallback(
    async (reader: ReadableStreamDefaultReader<Uint8Array>, gen: number) => {
      const decoder = new TextDecoder();
      let buffer = "";
      try {
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
              dispatchStreamEvent(event, gen);
            } catch {
              // ignore malformed JSON
            }
          }
        }
      } catch {
        // stream ended or aborted
      }
    },
    [dispatchStreamEvent],
  );

  // ═══════════════════════════════════════════════════
  //  interruptInternal (no gen bump, no reload)
  // ═══════════════════════════════════════════════════

  const interruptInternal = useCallback(
    async (sid: string) => {
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      try {
        await fetch(`/api/session/${sid}/interrupt`, { method: "POST" });
      } catch {
        // ignore network errors
      }
      setActive((prev) => {
        if (prev) appendCompleted({ ...prev, status: "complete" as const });
        return null;
      });
      setRunning(false);
      setInterrupting(false);
    },
    [appendCompleted],
  );

  // ═══════════════════════════════════════════════════
  //  interrupt (public) — idempotent, returns Promise
  // ═══════════════════════════════════════════════════

  const interrupt = useCallback(async (): Promise<void> => {
    if (!sessionId || !runningRef.current) return;
    // NOTE: intentionally NOT checking opGuardRef here.
    // send() holds opGuardRef while blocked on readSSEStream (e.g.
    // during a long-running tool like sleep). If interrupt were gated
    // by opGuardRef, the Stop button silently does nothing.
    // Instead we always allow interrupt — it aborts the SSE stream
    // first (via abortRef), causing send() to unwind and release the lock.
    const gen = bumpGen();
    setInterrupting(true);
    try {
      await interruptInternal(sessionId);
      await reloadMessagesInternal(sessionId, gen);
    } finally {
      // No opGuardRef clearing here — interrupt is lock-free by design
    }
  }, [sessionId, interruptInternal, reloadMessagesInternal]);

  // ═══════════════════════════════════════════════════
  //  send — 统一发送入口
  // ═══════════════════════════════════════════════════

  const send = useCallback(
    async (question: string): Promise<void> => {
      if (opGuardRef.current) return;
      opGuardRef.current = true;
      const gen = bumpGen();

      try {
        setRunError(null);
        const prefill = prefillRef.current.trim();
        if (prefill) prefillRef.current = "";
        const q = (prefill ? prefill + "\n" + question : question).trim();
        if (!q) return;

        // Ensure session exists
        let sid = sessionId;
        let selfStarted = false;
        if (!sid) {
          sid = await createSession();
          // CRITICAL: set runningRef + streamSidRef *before* onSessionCreated,
          // so the session-switch useEffect sees them and bails out instead of
          // bumping gen / clearing messages / reloading.
          selfStarted = true;
          runningRef.current = true;
          streamSidRef.current = sid;
          onSessionCreated?.(sid);
        }

        // Interrupt any running stream (skip if we just created this session)
        if (!selfStarted && runningRef.current) {
          await interruptInternal(sid!);
        }

        setRunning(true);
        setInterrupting(false);
        streamSidRef.current = sid!;
        chatStreamActiveRef.current = true;

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
            if (streamRes.status === 409) {
              setRunError(BUSY_MESSAGE);
              return;
            }
            throw new Error(
              `Server returned ${streamRes.status}`,
            );
          }
          await readSSEStream(streamRes.body!.getReader(), gen);
        } catch (err) {
          if (err instanceof DOMException && err.name === "AbortError") return;
          throw err;
        } finally {
          if (abortRef.current === controller) {
            abortRef.current = null;
          }
          chatStreamActiveRef.current = false;
          if (genRef.current === gen && runningRef.current) {
            setRunning(false);
          }
        }
      } finally {
        opGuardRef.current = false;
      }
    },
    [
      sessionId,
      createSession,
      onSessionCreated,
      interruptInternal,
      readSSEStream,
    ],
  );

  // ═══════════════════════════════════════════════════
  //  resetRunning — emergency escape hatch
  // ═══════════════════════════════════════════════════

  const resetRunning = useCallback(() => {
    setRunning(false);
    setInterrupting(false);
  }, []);

  // ═══════════════════════════════════════════════════
  //  scrollToMessage
  // ═══════════════════════════════════════════════════

  const scrollToMessage = useCallback(
    (id: string) => {
      const container = scrollContainerRef?.current;
      if (!container) return;
      const el = container.querySelector(`[data-message-id="${id}"]`);
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    },
    [scrollContainerRef],
  );

  // ═══════════════════════════════════════════════════
  //  Session switch effect
  // ═══════════════════════════════════════════════════

  useEffect(() => {
    const prev = prevSidRef.current;
    prevSidRef.current = sessionId;

    if (prev === sessionId) return;

    // Session cleared
    if (!sessionId) {
      bumpGen();
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      setCompleted([]);
      completedIdsRef.current = new Set();
      setActive(null);
      setRunning(false);
      streamSidRef.current = null;
      return;
    }

    // If currently streaming on this exact session, don't interfere
    if (runningRef.current && streamSidRef.current === sessionId) return;

    // Switch to different session
    const gen = bumpGen();
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setCompleted([]);
    completedIdsRef.current = new Set();
    setActive(null);
    setRunning(false);
    streamSidRef.current = null;
    reloadMessagesInternal(sessionId, gen);
  }, [sessionId, reloadMessagesInternal]);

  // ═══════════════════════════════════════════════════
  //  Auto-reconnect effect (page refresh while running)
  // ═══════════════════════════════════════════════════

  useEffect(() => {
    if (!sessionId) return;
    if (!running) return;
    if (abortRef.current) return;
    if (chatStreamActiveRef.current) return;

    const sid = sessionId;
    const gen = genRef.current;
    const controller = new AbortController();
    abortRef.current = controller;

    (async () => {
      try {
        const res = await fetch(`/api/session/${sid}/stream`, {
          signal: controller.signal,
        });
        if (!res.ok || !res.body) return;
        await readSSEStream(res.body.getReader(), gen);
      } catch {
        // stream ended or aborted
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
        if (genRef.current === gen && runningRef.current) {
          setRunning(false);
        }
      }
    })();

    return () => controller.abort();
  }, [sessionId, running, readSSEStream]);

  // ═══════════════════════════════════════════════════
  //  Return
  // ═══════════════════════════════════════════════════

  return {
    running,
    interrupting,
    messages,
    activeMessage: active,
    send,
    interrupt,
    reloadMessages,
    truncateMessages,
    resetRunning,
    createSession,
    prefillRef,
    scrollToMessage,
    runError,
    clearRunError,
  };
}
