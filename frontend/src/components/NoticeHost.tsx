import { useEffect, useMemo, useState } from "react";
import Icon from "./Icon";

export type NoticeLevel = "info" | "warn" | "error" | "success";

export interface Notice {
  id: string;
  level: NoticeLevel;
  title: string;
  detail?: string;
  progress?: string;
  retryAfterMs?: number;
  retryAt?: number;
  updatedAt: number;
  ttlMs: number;
  sticky?: boolean;
  exiting?: boolean;
}

interface NoticeHostProps {
  notices: Notice[];
  onDismiss: (id: string) => void;
}

function iconFor(level: NoticeLevel) {
  if (level === "success") return "check";
  if (level === "error" || level === "warn") return "error";
  return "diamond";
}

function formatRetryCountdown(ms: number) {
  if (ms <= 0) return "retrying now";
  const seconds = ms / 1000;
  if (seconds < 10) return `retrying in ${seconds.toFixed(1)}s`;
  return `retrying in ${Math.ceil(seconds)}s`;
}

export default function NoticeHost({ notices, onDismiss }: NoticeHostProps) {
  const hasCountdown = useMemo(
    () => notices.some((notice) => notice.retryAt && notice.retryAt > Date.now()),
    [notices],
  );
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!hasCountdown) return;
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [hasCountdown]);

  if (!notices.length) return null;

  return (
    <div className="agent-notice-host" aria-live="polite" aria-atomic="false">
      {notices.map((notice) => {
        const retryRemaining =
          notice.retryAt != null ? Math.max(0, notice.retryAt - now) : 0;
        const retryText =
          notice.retryAt != null ? formatRetryCountdown(retryRemaining) : "";
        const detail = [notice.detail, retryText].filter(Boolean).join(" · ");
        return (
          <div
            key={notice.id}
            className={`agent-notice agent-notice--${notice.level}${
              notice.exiting ? " agent-notice--exiting" : ""
            }`}
            role={notice.level === "error" ? "alert" : "status"}
          >
            <div className="agent-notice-icon">
              <Icon name={iconFor(notice.level)} size={14} />
            </div>
            <div className="agent-notice-main">
              <div className="agent-notice-title-row">
                <span className="agent-notice-title">{notice.title}</span>
                {notice.progress && (
                  <span className="agent-notice-progress">{notice.progress}</span>
                )}
              </div>
              {detail && (
                <div className="agent-notice-detail">{detail}</div>
              )}
            </div>
            <button
              type="button"
              className="agent-notice-dismiss"
              aria-label="Dismiss notice"
              onClick={() => onDismiss(notice.id)}
            >
              <Icon name="x" size={12} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
