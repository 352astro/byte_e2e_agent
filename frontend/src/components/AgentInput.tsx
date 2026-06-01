import { useState, useRef } from "react";

interface AgentInputProps {
    running: boolean;
    runtimeBusy: boolean;
    interrupting: boolean;
    prefillRef: React.MutableRefObject<string>;
    prefillContent: string;
    onPrefillChange: (v: string) => void;
    onSend: (question: string) => void;
    onInterrupt: () => void;
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
}: AgentInputProps) {
    const [question, setQuestion] = useState("");
    const [rows, setRows] = useState(1);
    const composingRef = useRef(false);
    const MAX_ROWS = 10;

    const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        setQuestion(e.target.value);
        setRows(
            Math.min(Math.max(e.target.value.split("\n").length, 1), MAX_ROWS),
        );
    };

    const doSend = (content: string) => {
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
