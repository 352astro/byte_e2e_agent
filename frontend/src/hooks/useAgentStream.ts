import { useState, useRef, useCallback, useEffect } from "react";
import type { Message, SessionCache, StreamEvent, RecoverData } from "../types";
import { reduceMessages } from "./messageReducer";

// ── types ────────────────────────────────────────────

interface UseAgentStreamOptions {
  sessionId: string | null;
  cache?: SessionCache;
  scrollContainerRef?: React.RefObject<HTMLDivElement | null>;
}

interface UseAgentStreamReturn {
  running: boolean;
  messages: Message[];
  handleRun: (sid: string, question: string) => Promise<void>;
  createSession: () => Promise<string>;
  prefillRef: React.MutableRefObject<string>;
  reloadMessages: () => void;
  truncateMessages: (truncateTid: string, keep?: boolean) => void;
  handleInterrupt: () => Promise<void>;
  resetRunning: () => void;
  interrupting: boolean;
  scrollToMessage: (id: string) => void;
}

// ── hook ──────────────────────────────────────────────

export default function useAgentStream({
  sessionId,
  cache = {},
  scrollContainerRef,
}: UseAgentStreamOptions): UseAgentStreamReturn {
  const [running, _setRunning] = useState(false);
  const setRunning = (v: boolean) => {
    runningRef.current = v;
    _setRunning(v);
  };
  const [messages, setMessages] = useState<Message[]>([]);
  const [interrupting, setInterrupting] = useState(false);
  const [activeSid, setActiveSid] = useState<string | null>(sessionId);

  const abortRef = useRef<AbortController | null>(null);
  const lastIdRef = useRef<string | null>(null);
  const fetchForRef = useRef<string | null>(null);
  const streamingSidRef = useRef<string | null>(null);
  const runningRef = useRef(false);
  const prefillRef = useRef<string>("");

  // ── createSession ──────────────────────────────────

  const createSession = useCallback(async (): Promise<string> => {
    const res = await fetch("/api/session", { method: "POST" });
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const data = await res.json();
    return data.session_id as string;
  }, []);

  // ── reload ─────────────────────────────────────────

  const reloadMessages = useCallback((): Promise<void> => {
    if (!sessionId) return Promise.resolve();
    const fetchFor = sessionId;
    fetchForRef.current = fetchFor;
    return fetch(`/api/session/${sessionId}/recover`)
      .then((r) => r.json())
      .then((data: RecoverData) => {
        if (fetchForRef.current !== fetchFor) return;
        const msgs: Message[] = data.messages || [];
        setMessages(msgs);
        if (data.running) setRunning(true);
        setInterrupting(false);
        lastIdRef.current = msgs.length ? msgs[msgs.length - 1].id : null;
        cache[sessionId] = {
          messages: msgs,
          _complete: !data.running,
        };
      });
  }, [sessionId, cache]);

  const truncateMessages = useCallback(
    (truncateTid: string, keep = false) => {
      if (!sessionId || !truncateTid) return;
      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.id === truncateTid);
        if (idx < 0) return prev;
        const cutoff = keep ? idx + 1 : idx;
        if (cutoff >= prev.length) return prev;
        const kept = prev.slice(0, cutoff);
        lastIdRef.current = kept.length ? kept[kept.length - 1].id : null;
        cache[sessionId] = { messages: kept, _complete: true };
        return kept;
      });
    },
    [sessionId, cache],
  );

  // ── session switch ─────────────────────────────────

  // 跟踪上一次 sessionId，用于检测真正的切换
  const prevSidRef = useRef<string | null>(sessionId);

  useEffect(() => {
    const prev = prevSidRef.current;
    prevSidRef.current = sessionId;

    // 同一个 session（包括首次渲染或 parent re-render）— 不动作
    if (prev === sessionId) return;

    // 切换到 null（清空）
    if (!sessionId) {
      setMessages([]);
      setRunning(false);
      setActiveSid(null);
      return;
    }

    // 从 null 或另一个 session 切换到新 sessionId
    setActiveSid(sessionId);

    const cached = cache[sessionId];
    if (cached && cached.messages) {
      setMessages(cached.messages);
      if (!cached._complete) setRunning(true);
      lastIdRef.current = cached.messages.length
        ? cached.messages[cached.messages.length - 1].id
        : null;
    } else {
      setMessages([]);
      setRunning(false);
      reloadMessages().catch((err) => {
        console.error("reloadMessages failed", err);
      });
    }
  }, [sessionId]);

  // ── scroll ─────────────────────────────────────────

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

  // ── interrupt ──────────────────────────────────────

  const handleInterrupt = useCallback(async () => {
    const sid = activeSid || sessionId;
    if (!sid || !runningRef.current || interrupting) return;
    setInterrupting(true);
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    try {
      await fetch(`/api/session/${sid}/interrupt`, { method: "POST" });
    } catch {
      // ignore network errors during interrupt
    }
    setRunning(false);
    runningRef.current = false;
    setInterrupting(false);
    streamingSidRef.current = null;
    reloadMessages();
  }, [interrupting, reloadMessages, sessionId, activeSid]);

  // ── SSE event dispatch ─────────────────────────────

  const dispatchStreamEvent = useCallback((ev: StreamEvent) => {
    switch (ev.kind) {
      case "message_start":
      case "chunk_delta":
      case "chunk_complete":
      case "message_finish": {
        setMessages((prev) => reduceMessages(prev, ev));
        if (ev.kind === "message_finish") {
          lastIdRef.current = ev.message_id;
        }
        break;
      }
      case "turn_complete":
      case "interrupted": {
        setRunning(false);
        break;
      }
    }
  }, []);

  // ── auto-reconnect stream ──────────────────────────

  useEffect(() => {
    if (!sessionId) return;
    if (!running) return;
    const sid = sessionId;

    const controller = new AbortController();

    (async () => {
      try {
        const res = await fetch(`/api/session/${sid}/stream`, {
          signal: controller.signal,
        });
        if (!res.ok || !res.body) return;
        const reader = res.body.getReader();
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
      } catch {
        // stream ended or aborted
      }
    })();

    return () => controller.abort();
  }, [sessionId, running, dispatchStreamEvent]);

  // ── handleRun ──────────────────────────────────────

  const handleRun = useCallback(
    async (sid: string, question: string) => {
      const prefill = prefillRef.current.trim();
      if (prefill) prefillRef.current = "";
      const q = (prefill ? prefill + "\n" + question : question).trim();
      if (!q || !sid || runningRef.current) return;

      setRunning(true);
      setInterrupting(false);

      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
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
        if (err instanceof DOMException && err.name === "AbortError") return;
      } finally {
        if (abortRef.current !== controller) return;
        abortRef.current = null;
        streamingSidRef.current = null;
        if (runningRef.current) {
          setRunning(false);
        }
      }
    },
    [dispatchStreamEvent],
  );

  const resetRunning = useCallback(() => {
    setRunning(false);
    setInterrupting(false);
  }, []);

  return {
    running,
    interrupting,
    messages,
    handleRun,
    createSession,
    prefillRef,
    reloadMessages,
    truncateMessages,
    handleInterrupt,
    resetRunning,
    scrollToMessage,
  };
}
