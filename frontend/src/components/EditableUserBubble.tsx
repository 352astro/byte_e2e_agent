import React from "react";
import { useState, useRef, useEffect } from "react";

interface EditableUserBubbleProps {
  content: string;
  onEditSubmit: (content: string) => void;
}

const EditableUserBubble = React.memo(function EditableUserBubble({
  content,
  onEditSubmit,
}: EditableUserBubbleProps) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(content);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const composingRef = useRef(false);

  // Resync when content prop changes externally and we're not editing
  useEffect(() => {
    if (!editing) setValue(content);
  }, [content, editing]);

  // Auto-resize on mount and when value changes
  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = el.scrollHeight + "px";
    }
  }, [value]);

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
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
      e.preventDefault();
      textareaRef.current?.blur();
      return;
    }
    if (e.key === "Enter" && !e.shiftKey && !composingRef.current) {
      e.preventDefault();
      submit();
    }
  };

  const handleFocus = () => {
    setValue(content);
    setEditing(true);
  };

  const handleBlur = () => {
    cancel();
  };

  return (
    <div className={`user-bubble${editing ? " user-bubble--editing" : ""}`}>
      <span className="user-bubble-label">You</span>
      <textarea
        ref={textareaRef}
        className="user-bubble-edit"
        value={value}
        onChange={handleInput}
        onKeyDown={handleKeyDown}
        onFocus={handleFocus}
        onBlur={handleBlur}
        onCompositionStart={() => {
          composingRef.current = true;
        }}
        onCompositionEnd={() => {
          composingRef.current = false;
        }}
        readOnly={!editing}
        rows={1}
        cols={Math.max(1, ...value.split("\n").map(l => l.length)) + 6}
      />
    </div>
  );
});

export default EditableUserBubble;

