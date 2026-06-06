import { useState, useEffect, useRef, useCallback } from "react";
import type { GuardRequest } from "../types";

interface Notice {
  id: string;
  level: "info" | "warn" | "error" | "success";
  title: string;
  detail: string;
  progress: string;
  retryAfterMs: number;
  retryAt: number;
  ttlMs: number;
  sticky: boolean;
  sessionId: string;
  updatedAt: number;
  exiting?: boolean;
}

interface UseNotificationsReturn {
  pendingGuard: GuardRequest | null;
  respondGuard: (
    requestId: string,
    response: Record<string, unknown>,
  ) => Promise<void>;
  notices: Notice[];
  dismissNotice: (id: string) => void;
  connected: boolean;
}

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 16000;

export function useNotifications(
  sessionId: string | null,
): UseNotificationsReturn {
  const [pendingGuard, setPendingGuard] = useState<GuardRequest | null>(null);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [connected, setConnected] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const retryCountRef = useRef(0);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sessionIdRef = useRef(sessionId);
  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  const connect = useCallback(() => {
    if (controllerRef.current) {
      controllerRef.current.abort();
    }
    const controller = new AbortController();
    controllerRef.current = controller;

    const run = async () => {
      try {
        // Fetch recover state first
        const recoverRes = await fetch("/api/notifications/recover", {
          signal: controller.signal,
        });
        if (recoverRes.ok) {
          const data = await recoverRes.json();
          if (data.pending_guard) {
            const guard = data.pending_guard as GuardRequest;
            const currentSid = sessionIdRef.current;
            if (
              currentSid &&
              guard.session_id &&
              guard.session_id !== currentSid
            ) {
              (guard as Record<string, unknown>)._comeFromSid =
                guard.session_id;
            }
            setPendingGuard(guard);
          }
          if (data.notices) {
            const now = Date.now();
            setNotices(
              (data.notices as Notice[]).filter(
                (n) => n.sticky || now - n.updatedAt < n.ttlMs,
              ),
            );
          }
        }
      } catch {
        // ignore recover failures
      }

      // Open SSE stream
      try {
        const streamRes = await fetch("/api/notifications/stream", {
          signal: controller.signal,
        });
        if (!streamRes.ok || !streamRes.body) throw new Error("Stream failed");

        setConnected(true);
        retryCountRef.current = 0;

        const reader = streamRes.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() || "";
          for (const part of parts) {
            const line = part.trim();
            if (!line.startsWith("data: ")) continue;
            const raw = line.slice(6);
            if (raw === '{"kind":"heartbeat"}') continue;
            try {
              const ev = JSON.parse(raw);
              if (ev.kind === "guard_request") {
                const guard = JSON.parse(ev.full_content) as GuardRequest;
                const currentSid = sessionIdRef.current;
                if (
                  currentSid &&
                  guard.session_id &&
                  guard.session_id !== currentSid
                ) {
                  (guard as Record<string, unknown>)._comeFromSid =
                    guard.session_id;
                }
                setPendingGuard(guard);
              } else if (ev.kind === "runtime_notice") {
                const notice: Notice = {
                  id: ev.notice_id || "",
                  level: ev.level || "info",
                  title: ev.title || "",
                  detail: ev.detail || "",
                  progress: ev.progress || "",
                  retryAfterMs: ev.retry_after_ms || 0,
                  retryAt: ev.retry_at || 0,
                  ttlMs: ev.ttl_ms || 4500,
                  sticky: ev.sticky || false,
                  sessionId: ev.session_id || "",
                  updatedAt: Date.now(),
                };
                setNotices((prev) => {
                  const idx = prev.findIndex((n) => n.id === notice.id);
                  if (idx >= 0) {
                    const next = [...prev];
                    next[idx] = { ...next[idx], ...notice };
                    return next;
                  }
                  return [...prev, notice];
                });
              }
            } catch {
              // skip malformed events
            }
          }
        }
      } catch {
        // stream ended, will reconnect
      } finally {
        setConnected(false);
      }
    };

    run().catch(() => {});

    return () => controller.abort();
  }, []);

  // Initial connect + reconnect
  useEffect(() => {
    let aborted = false;

    const tryConnect = () => {
      if (aborted) return;
      connect();
    };

    const scheduleReconnect = () => {
      if (aborted) return;
      const delay = Math.min(
        RECONNECT_BASE_MS * Math.pow(2, retryCountRef.current),
        RECONNECT_MAX_MS,
      );
      retryCountRef.current += 1;
      retryTimerRef.current = setTimeout(tryConnect, delay);
    };

    tryConnect();

    // Listen for stream end to reconnect
    const checkConnection = () => {
      scheduleReconnect();
    };

    return () => {
      aborted = true;
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
      if (controllerRef.current) controllerRef.current.abort();
    };
  }, [connect]);

  // Reconnect on visibility change
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible" && !connected) {
        retryCountRef.current = 0;
        connect();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [connect, connected]);

  const respondGuard = useCallback(
    async (
      requestId: string,
      response: Record<string, unknown>,
    ): Promise<void> => {
      try {
        const res = await fetch(`/api/notifications/respond/${requestId}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ response }),
        });
        if (!res.ok) throw new Error(`Server returned ${res.status}`);
      } finally {
        setPendingGuard(null);
      }
    },
    [],
  );

  const dismissNotice = useCallback((id: string) => {
    setNotices((prev) =>
      prev.map((n) => (n.id === id ? { ...n, exiting: true } : n)),
    );
    // Remove after animation
    setTimeout(() => {
      setNotices((prev) => prev.filter((n) => n.id !== id));
    }, 300);
  }, []);

  return {
    pendingGuard,
    respondGuard,
    notices,
    dismissNotice,
    connected,
  };
}
