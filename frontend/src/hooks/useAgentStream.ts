import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import type {
  CreateSessionRequest,
  GuardRequest,
  Message,
  RecoverData,
  StreamEvent,
} from "../types";

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
  runtimeBusy: boolean;
  interrupting: boolean;
  messages: Message[];
  activeMessage: Message | null;

  // ── 命令（异步）──
  send: (
    question: string,
    sessionConfig?: CreateSessionRequest,
  ) => Promise<void>;
  interrupt: () => Promise<void>;
  reloadMessages: () => Promise<void>;
  respondGuard: (requestId: string, allow: boolean) => Promise<void>;

  // ── 命令（同步）──
  truncateMessages: (truncateTid: string, keep?: boolean) => void;
  resetRunning: () => void;

  // ── 工具 ──
  createSession: (config: CreateSessionRequest) => Promise<string>;
  prefillRef: React.MutableRefObject<string>;
  scrollToMessage: (id: string) => void;
  runError: string | null;
  clearRunError: () => void;
  pendingGuard: GuardRequest | null;
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
    tool_status: "success",
    tool_status_source: "tool",
    tool_status_reason: "",
    error: "",
  } as Message;
}

function emptyTC(): Record<string, unknown> {
  return { id: "", type: "function", function: { name: "", arguments: "" } };
}

function applyToolMeta(message: Message, raw: string): Message {
  let meta: Record<string, unknown>;
  try {
    meta = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return message;
  }
  const tcs = [...(message.tool_calls || [])] as Record<string, any>[];
  if (!tcs.length) return message;

  const targetToolCallId = String(meta.parent_tool_call_id || "");
  let idx = targetToolCallId
    ? tcs.findIndex((tc) => tc.id === targetToolCallId)
    : -1;
  if (idx < 0) {
    idx = tcs.findIndex((tc) => tc.function?.name === "SubAgent");
  }
  if (idx < 0) return message;

  const existing = (tcs[idx].tool_meta || {}) as Record<string, unknown>;
  tcs[idx] = {
    ...tcs[idx],
    tool_meta: {
      ...existing,
      ...meta,
    },
  };
  return { ...message, tool_calls: tcs as any };
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
  const [runtimeBusy, setRuntimeBusy] = useState(false);
  const [completed, setCompleted] = useState<Message[]>([]);
  const [active, setActive] = useState<Message | null>(null);
  const [interrupting, setInterrupting] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [pendingGuard, setPendingGuard] = useState<GuardRequest | null>(null);

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
  const pendingToolMetaRef = useRef<Map<string, string[]>>(new Map());

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

  const applyPendingToolMeta = useCallback((msg: Message) => {
    const pending = pendingToolMetaRef.current.get(msg.id);
    if (!pending?.length) return msg;
    let next = msg;
    for (const raw of pending) {
      next = applyToolMeta(next, raw);
    }
    pendingToolMetaRef.current.delete(msg.id);
    return next;
  }, []);

  const appendCompleted = useCallback(
    (msg: Message) => {
      setCompleted((prev) => {
        const nextMsg = applyPendingToolMeta(msg);
        if (prev.some((m) => m.id === nextMsg.id)) return prev;
        completedIdsRef.current.add(nextMsg.id);
        return [...prev, nextMsg];
      });
    },
    [applyPendingToolMeta],
  );

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

  const createSession = useCallback(
    async (config: CreateSessionRequest): Promise<string> => {
      const res = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();
      return data.session_id as string;
    },
    [],
  );

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
        setRuntimeBusy(Boolean(data.runtime_busy));
        setPendingGuard(data.pending_request?.message || null);
        if (data.session_running) {
          setRunning(true);
          streamSidRef.current = sid;
        } else {
          setRunning(false);
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
          if (field === "tool_meta") {
            const pending = pendingToolMetaRef.current.get(ev.message_id) || [];
            pending.push(full_content);
            pendingToolMetaRef.current.set(ev.message_id, pending);
            setCompleted((prev) =>
              prev.map((msg) =>
                msg.id === ev.message_id
                  ? applyToolMeta(msg, full_content)
                  : msg,
              ),
            );
            setActive((prev) =>
              prev && prev.id === ev.message_id
                ? applyToolMeta(prev, full_content)
                : prev,
            );
            break;
          }
          setActive((prev) => {
            if (!prev || prev.id !== ev.message_id) return prev;
            const next = { ...prev, [field]: full_content };
            if (field === "tool_result") {
              return {
                ...next,
                tool_status: ev.tool_status || prev.tool_status || "success",
                tool_status_source:
                  ev.tool_status_source || prev.tool_status_source || "tool",
                tool_status_reason:
                  ev.tool_status_reason || prev.tool_status_reason || "",
              };
            }
            return next;
          });
          break;
        }

        case "guard_request": {
          if (genRef.current !== gen) return;
          try {
            setPendingGuard(JSON.parse(ev.full_content) as GuardRequest);
          } catch {
            setPendingGuard({
              request_id: ev.message_id,
              action_type: "unknown",
              subject: ev.tool_name || "unknown",
              payload: {},
            });
          }
          break;
        }

        case "message_finish": {
          if (genRef.current !== gen) return;
          setActive((prev) => {
            if (!prev || prev.id !== ev.message_id) return prev;
            const done = {
              ...prev,
              status: "complete" as const,
              _usage: ev.usage || (prev as Record<string, unknown>)?._usage,
            };
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
          setRuntimeBusy(false);
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
      setRuntimeBusy(false);
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

  const respondGuard = useCallback(
    async (requestId: string, allow: boolean): Promise<void> => {
      if (!sessionId) return;
      const res = await fetch(`/api/session/${sessionId}/respond`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message_id: requestId,
          response: { allow },
        }),
      });
      if (!res.ok) {
        setRunError(`Permission response failed: ${res.status}`);
        return;
      }
      setPendingGuard(null);
    },
    [sessionId],
  );

  // ═══════════════════════════════════════════════════
  //  send — 统一发送入口
  // ═══════════════════════════════════════════════════

  const send = useCallback(
    async (
      question: string,
      sessionConfig: CreateSessionRequest = {
        name: "",
        preamble: "",
        rules: [],
        preloaded_skills: [],
        tool_set_preset: "all",
        custom_tools: [],
      },
    ): Promise<void> => {
      if (opGuardRef.current) return;
      opGuardRef.current = true;
      const gen = bumpGen();

      try {
        setRunError(null);
        setPendingGuard(null);
        const prefill = prefillRef.current.trim();
        if (prefill) prefillRef.current = "";
        const q = (prefill ? prefill + "\n" + question : question).trim();
        if (!q) return;

        // Ensure session exists
        let sid = sessionId;
        let selfStarted = false;
        if (!sid) {
          sid = await createSession(sessionConfig);
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
        setRuntimeBusy(true);
        setInterrupting(false);
        streamSidRef.current = sid!;
        chatStreamActiveRef.current = true;

        const controller = new AbortController();
        abortRef.current = controller;
        let keepRuntimeBusy = false;

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
              setRunning(false);
              setRuntimeBusy(true);
              keepRuntimeBusy = true;
              setRunError(BUSY_MESSAGE);
              return;
            }
            throw new Error(`Server returned ${streamRes.status}`);
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
          if (genRef.current === gen && !keepRuntimeBusy) {
            setRuntimeBusy(false);
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
    setRuntimeBusy(false);
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
      setPendingGuard(null);
      setRunning(false);
      setRuntimeBusy(false);
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
    setPendingGuard(null);
    setRunning(false);
    setRuntimeBusy(false);
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
        if (genRef.current === gen) {
          setRuntimeBusy(false);
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
    runtimeBusy,
    interrupting,
    messages,
    activeMessage: active,
    send,
    interrupt,
    reloadMessages,
    respondGuard,
    truncateMessages,
    resetRunning,
    createSession,
    prefillRef,
    scrollToMessage,
    runError,
    clearRunError,
    pendingGuard,
  };
}
