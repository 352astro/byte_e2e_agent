import { useState, useRef, useEffect } from "react";

interface EditableUserBubbleProps {
    content: string;
    onEditSubmit: (content: string) => void;
}

export default function EditableUserBubble({
    content,
    onEditSubmit,
}: EditableUserBubbleProps) {
    const [editing, setEditing] = useState(false);
    const [value, setValue] = useState(content);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const composingRef = useRef(false);

    // Resync when content prop changes externally
    useEffect(() => {
        if (!editing) setValue(content);
    }, [content, editing]);

    // Auto-focus and resize textarea on edit start
    useEffect(() => {
        if (editing && textareaRef.current) {
            const el = textareaRef.current;
            el.focus();
            el.setSelectionRange(el.value.length, el.value.length);
            el.style.height = "auto";
            el.style.height = el.scrollHeight + "px";
        }
    }, [editing]);

    const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        setValue(e.target.value);
        const el = e.target;
        el.style.height = "auto";
        el.style.height = el.scrollHeight + "px";
    };

    const submit = () => {
        const trimmed = value.trim();
        if (!trimmed) return;
        setEditing(false);
        onEditSubmit(trimmed);
    };

    const cancel = () => {
        setEditing(false);
        setValue(content);
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === "Escape") {
            cancel();
            return;
        }
        if (e.key === "Enter" && !e.shiftKey && !composingRef.current) {
            e.preventDefault();
            submit();
        }
    };

    if (editing) {
        return (
            <div className="user-bubble user-bubble--editing">
                <span className="user-bubble-label">You</span>
                <textarea
                    ref={textareaRef}
                    className="user-bubble-edit"
                    value={value}
                    onChange={handleInput}
                    onKeyDown={handleKeyDown}
                    onBlur={cancel}
                    onCompositionStart={() => {
                        composingRef.current = true;
                    }}
                    onCompositionEnd={() => {
                        composingRef.current = false;
                    }}
                    rows={1}
                />
            </div>
        );
    }

    return (
        <div
            className="user-bubble"
            onClick={() => {
                setValue(content);
                setEditing(true);
            }}
            title="Click to edit"
        >
            <span className="user-bubble-label">You</span>
            <p>{content}</p>
        </div>
    );
}
