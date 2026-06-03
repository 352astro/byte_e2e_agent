import { useState, useRef } from "react";
import SessionCustomizePanel from "./SessionCustomizePanel";
import Icon from "./Icon";
import type { CreateSessionRequest } from "../types";

interface AgentInputProps {
    running: boolean;
    runtimeBusy: boolean;
    interrupting: boolean;
    prefillRef: React.MutableRefObject<string>;
    prefillContent: string;
    onPrefillChange: (v: string) => void;
    onSend: (question: string) => void;
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
    prefillRef,
    prefillContent,
    onPrefillChange,
    onSend,
    onInterrupt,
    sessionConfig,
    onSessionConfigChange,
    showCustomize = false,
    customizeReadonly = false,
}: AgentInputProps) {
    const [question, setQuestion] = useState("");
    const [rows, setRows] = useState(1);
    const [customizeOpen, setCustomizeOpen] = useState(true);
    const composingRef = useRef(false);
    const MAX_ROWS = 10;

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
                <div className="agent-input-bar-inner">
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
