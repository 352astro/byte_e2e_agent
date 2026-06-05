import { useEffect, useState, useRef } from "react";
import SessionCustomizePanel from "./SessionCustomizePanel";
import Icon from "./Icon";
import type { CreateSessionRequest } from "../types";

interface AgentInputProps {
    running: boolean;
    runtimeBusy: boolean;
    interrupting: boolean;
    queuedSends: string[];
    prefillRef: React.MutableRefObject<string>;
    prefillContent: string;
    onPrefillChange: (v: string) => void;
    onSend: (question: string) => void;
    onSendNow: (question?: string) => void;
    onClearQueue: () => void;
    onUpdateQueue: (index: number, value: string) => void;
    onInterrupt: () => void;
    sessionConfig?: CreateSessionRequest;
    onSessionConfigChange?: (next: CreateSessionRequest) => void;
    showCustomize?: boolean;
    customizeReadonly?: boolean;
}

export default function AgentInput({
    running,
    runtimeBusy,
    interrupting,
    queuedSends,
    prefillRef,
    prefillContent,
    onPrefillChange,
    onSend,
    onSendNow,
    onClearQueue,
    onUpdateQueue,
    onInterrupt,
    sessionConfig,
    onSessionConfigChange,
    showCustomize = false,
    customizeReadonly = false,
}: AgentInputProps) {
    const [question, setQuestion] = useState("");
    const [rows, setRows] = useState(1);
    const [customizeOpen, setCustomizeOpen] = useState(
        showCustomize && !customizeReadonly,
    );
    const [renderedQueue, setRenderedQueue] = useState<
        { key: string; text: string; index: number; exiting: boolean }[]
    >([]);
    const composingRef = useRef(false);
    const MAX_ROWS = 10;

    useEffect(() => {
        const nextItems = queuedSends.map((text, idx) => ({
            key: String(idx),
            text,
            index: idx,
            exiting: false,
        }));
        const nextKeys = new Set(nextItems.map((item) => item.key));

        setRenderedQueue((prev) => {
            const kept = prev
                .filter((item) => nextKeys.has(item.key) || !item.exiting)
                .map((item) =>
                    nextKeys.has(item.key)
                        ? {
                              ...nextItems.find((next) => next.key === item.key)!,
                              exiting: false,
                          }
                        : { ...item, exiting: true },
                );
            const keptKeys = new Set(kept.map((item) => item.key));
            const added = nextItems.filter((item) => !keptKeys.has(item.key));
            return [...kept, ...added];
        });

        const timer = window.setTimeout(() => {
            setRenderedQueue((prev) => prev.filter((item) => !item.exiting));
        }, 320);
        return () => window.clearTimeout(timer);
    }, [queuedSends]);

    useEffect(() => {
        setCustomizeOpen(showCustomize && !customizeReadonly);
    }, [customizeReadonly, showCustomize]);

    useEffect(() => {
        if (!customizeOpen) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") setCustomizeOpen(false);
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [customizeOpen]);

    const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        setQuestion(e.target.value);
        setRows(
            Math.min(Math.max(e.target.value.split("\n").length, 1), MAX_ROWS),
        );
    };

    const doSend = (content: string) => {
        if (runtimeBusy && !running) return;
        if (!content.trim()) return;
        setQuestion("");
        setRows(1);
        onSend(content);
    };

    const consumeQuestion = () => {
        const content = question;
        setQuestion("");
        setRows(1);
        return content;
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key !== "Enter") return;
        if (e.ctrlKey || e.metaKey || e.shiftKey) return;
        if (composingRef.current) return;
        e.preventDefault();

        if (prefillContent.trim()) {
            prefillRef.current = prefillContent.trim();
            onPrefillChange("");
        }
        doSend(question);
    };

    const handleSendClick = () => {
        if (running && !interrupting) {
            onInterrupt();
            return;
        }
        if (runtimeBusy) return;
        if (prefillContent.trim()) {
            prefillRef.current = prefillContent.trim();
            onPrefillChange("");
        }
        doSend(question);
    };

    const handleSendNow = () => {
        if (prefillContent.trim()) {
            prefillRef.current = prefillContent.trim();
            onPrefillChange("");
        }
        const content = consumeQuestion();
        onSendNow(content);
    };

    return (
        <>
            {/* Prefill bar (checkout / replay fills this) */}
            <div
                className={`agent-prefill${prefillContent.trim() ? " agent-prefill--open" : ""}`}
            >
                <div className="agent-prefill-inner">
                    <textarea
                        className="agent-prefill-textarea"
                        placeholder="(prefix)"
                        value={prefillContent}
                        onChange={(e) => onPrefillChange(e.target.value)}
                        onKeyDown={(e) => {
                            if (
                                e.key === "Enter" &&
                                !e.ctrlKey &&
                                !e.metaKey &&
                                !e.shiftKey
                            ) {
                                e.preventDefault();
                                if (prefillContent.trim()) {
                                    prefillRef.current = prefillContent.trim();
                                    onPrefillChange("");
                                    doSend(question);
                                }
                            }
                        }}
                        rows={1}
                    />
                    <button
                        className="agent-prefill-close"
                        onClick={() => onPrefillChange("")}
                    >
                        ×
                    </button>
                </div>
            </div>

            {/* Main input bar */}
            <div className="agent-input-bar">
                {renderedQueue.length > 0 && (
                    <div className="agent-send-queue">
                        <div className="agent-send-queue-header">
                            <div className="agent-send-queue-title">
                                {queuedSends.length} queued
                            </div>
                            <div className="agent-send-queue-actions">
                                <button
                                    type="button"
                                    onClick={handleSendNow}
                                    disabled={
                                        interrupting ||
                                        (!queuedSends.length && !question.trim())
                                    }
                                >
                                    Send now
                                </button>
                                <button
                                    type="button"
                                    onClick={onClearQueue}
                                    disabled={!queuedSends.length}
                                >
                                    Clear
                                </button>
                            </div>
                        </div>
                        <div className="agent-send-queue-list">
                            {renderedQueue.map((item) => (
                                <div
                                    key={item.key}
                                    className={`agent-send-queue-row${
                                        item.exiting
                                            ? " agent-send-queue-row--exiting"
                                            : ""
                                    }`}
                                >
                                    <span className="agent-send-queue-index">
                                        {item.exiting ? "" : item.index + 1}
                                    </span>
                                    <textarea
                                        className="agent-send-queue-text"
                                        value={item.text}
                                        disabled={item.exiting}
                                        rows={Math.min(
                                            Math.max(item.text.split("\n").length, 1),
                                            4,
                                        )}
                                        onChange={(e) => {
                                            onUpdateQueue(
                                                item.index,
                                                e.target.value,
                                            );
                                        }}
                                    />
                                </div>
                            ))}
                        </div>
                    </div>
                )}
                <div className="agent-input-bar-inner">
                    {showCustomize && sessionConfig && onSessionConfigChange && (
                        <div className="agent-customize-slot">
                            <button
                                className={`agent-customize-toggle${customizeOpen ? " active" : ""}`}
                                type="button"
                                onClick={() => setCustomizeOpen((v) => !v)}
                                title="Customize session"
                            >
                                <Icon name="palette" size={22} />
                            </button>
                            <div
                                className={`agent-customize-popover${customizeOpen ? " open" : ""}`}
                            >
                                <SessionCustomizePanel
                                    value={sessionConfig}
                                    onChange={onSessionConfigChange}
                                    mode="create"
                                    readonly={customizeReadonly}
                                />
                            </div>
                        </div>
                    )}
                    <textarea
                        className="agent-textarea"
                        placeholder="Ask the agent something… (Enter to send, Ctrl/Shift+Enter for newline)"
                        value={question}
                        onChange={handleChange}
                        onKeyDown={handleKeyDown}
                        onCompositionStart={() => {
                            composingRef.current = true;
                        }}
                        onCompositionEnd={() => {
                            composingRef.current = false;
                        }}
                        rows={rows}
                    />
                    <button
                        className={
                            interrupting
                                ? "agent-send-btn agent-send-btn--stopping"
                                : running
                                  ? "agent-send-btn agent-send-btn--stop"
                                  : "agent-send-btn"
                        }
                        onClick={handleSendClick}
                        disabled={
                            interrupting ||
                            (!running && runtimeBusy) ||
                            (!running &&
                                !question.trim() &&
                                !prefillContent.trim())
                        }
                    >
                        {interrupting
                            ? "Stopping…"
                            : running
                              ? "Stop"
                              : runtimeBusy
                                ? "Busy"
                                : "Send"}
                    </button>
                </div>
            </div>
        </>
    );
}
