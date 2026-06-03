import { useCallback, useEffect, useRef, useState } from "react";
import Icon from "./Icon";
import type { IconName } from "./Icon";
import "./WorkspacePickerModal.css";

type EntryKind = "directory" | "file" | "other";

interface WorkspaceEntry {
  name: string;
  path: string;
  kind: EntryKind;
  hidden: boolean;
  readable: boolean;
  size: number | null;
  modified_at: number | null;
}

interface DirectoryResponse {
  path: string;
  parent: string | null;
  home: string;
  roots: string[];
  entries: WorkspaceEntry[];
}

interface WorkspacePickerModalProps {
  initialPath: string;
  busy?: boolean;
  onClose: () => void;
  onSelect: (path: string) => Promise<void> | void;
}

function formatSize(size: number | null): string {
  if (size == null) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 * 1024 * 1024) {
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
  }
  return `${(size / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function formatModified(value: number | null): string {
  if (value == null) return "";
  return new Date(value * 1000).toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function iconForEntry(entry: WorkspaceEntry): IconName {
  if (entry.kind === "directory") return "folder";
  if (entry.kind === "file") return "file";
  return "diamond";
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

const MODAL_TOP = 48;
const MODAL_MARGIN = 20;
const TYPEAHEAD_RESET_MS = 700;

function clampDialogPosition(left: number, top: number, rect: DOMRect) {
  const maxLeft = Math.max(
    MODAL_MARGIN,
    window.innerWidth - rect.width - MODAL_MARGIN,
  );
  const maxTop = Math.max(
    MODAL_MARGIN,
    window.innerHeight - rect.height - MODAL_MARGIN,
  );
  return {
    left: Math.round(clamp(left, MODAL_MARGIN, maxLeft)),
    top: Math.round(clamp(top, MODAL_MARGIN, maxTop)),
  };
}

export default function WorkspacePickerModal({
  initialPath,
  busy = false,
  onClose,
  onSelect,
}: WorkspacePickerModalProps) {
  const [path, setPath] = useState(initialPath);
  const [inputPath, setInputPath] = useState(initialPath);
  const [parent, setParent] = useState<string | null>(null);
  const [home, setHome] = useState("");
  const [roots, setRoots] = useState<string[]>([]);
  const [entries, setEntries] = useState<WorkspaceEntry[]>([]);
  const [selectedPath, setSelectedPath] = useState(initialPath);
  const [showHidden, setShowHidden] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(
    null,
  );
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const typeaheadRef = useRef({ prefix: "", lastAt: 0 });
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originLeft: number;
    originTop: number;
  } | null>(null);
  const selectableEntries = entries.filter(
    (entry) => entry.kind === "directory" && entry.readable,
  );

  const focusList = useCallback(() => {
    window.requestAnimationFrame(() => {
      listRef.current?.focus({ preventScroll: true });
    });
  }, []);

  const loadDirectory = useCallback(
    async (
      nextPath: string,
      hidden = showHidden,
      options?: { focusList?: boolean },
    ) => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        if (nextPath) params.set("path", nextPath);
        params.set("show_hidden", hidden ? "true" : "false");
        const res = await fetch(`/api/workspace/ls?${params.toString()}`);
        if (!res.ok) {
          const detail = await res
            .json()
            .then((data) => data.detail)
            .catch(() => `Server returned ${res.status}`);
          throw new Error(detail);
        }
        const data: DirectoryResponse = await res.json();
        setPath(data.path);
        setInputPath(data.path);
        setSelectedPath(data.path);
        setParent(data.parent);
        setHome(data.home);
        setRoots(data.roots);
        setEntries(data.entries);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
        if (options?.focusList) focusList();
      }
    },
    [focusList, showHidden],
  );

  useEffect(() => {
    void loadDirectory(initialPath);
    // Initial path changes only when the modal is opened for a new workspace.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialPath]);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  useEffect(() => {
    const placeDialog = () => {
      const dialog = dialogRef.current;
      if (!dialog) return;

      const rect = dialog.getBoundingClientRect();
      setPosition((current) => {
        if (current) {
          return clampDialogPosition(current.left, current.top, rect);
        }
        return clampDialogPosition((window.innerWidth - rect.width) / 2, MODAL_TOP, rect);
      });
    };

    placeDialog();
    window.addEventListener("resize", placeDialog);
    return () => window.removeEventListener("resize", placeDialog);
  }, []);

  const close = useCallback(() => {
    if (!busy) onClose();
  }, [busy, onClose]);

  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      close();
    };

    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [close]);

  useEffect(() => {
    const handlePointerMove = (event: PointerEvent) => {
      const drag = dragRef.current;
      const dialog = dialogRef.current;
      if (!drag || !dialog || event.pointerId !== drag.pointerId) return;

      const rect = dialog.getBoundingClientRect();
      const nextLeft = drag.originLeft + event.clientX - drag.startX;
      const nextTop = drag.originTop + event.clientY - drag.startY;
      setPosition(clampDialogPosition(nextLeft, nextTop, rect));
    };

    const handlePointerUp = (event: PointerEvent) => {
      if (dragRef.current?.pointerId === event.pointerId) {
        dragRef.current = null;
      }
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerUp);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerUp);
    };
  }, []);

  const startDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    if ((event.target as HTMLElement).closest("button")) return;
    const rect = dialogRef.current?.getBoundingClientRect();
    const currentPosition = position ?? {
      left: rect?.left ?? MODAL_MARGIN,
      top: rect?.top ?? MODAL_TOP,
    };
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originLeft: currentPosition.left,
      originTop: currentPosition.top,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const isTextEntryTarget = (target: EventTarget | null): boolean => {
    if (!(target instanceof HTMLElement)) return false;
    return Boolean(target.closest("input, textarea, [contenteditable='true']"));
  };

  const selectByPrefix = (key: string) => {
    const now = window.performance.now();
    const state = typeaheadRef.current;
    const prefix =
      now - state.lastAt > TYPEAHEAD_RESET_MS
        ? key.toLocaleLowerCase()
        : `${state.prefix}${key}`.toLocaleLowerCase();

    state.prefix = prefix;
    state.lastAt = now;

    const match = entries.find(
      (entry) =>
        entry.kind === "directory" &&
        entry.readable &&
        entry.name.toLocaleLowerCase().startsWith(prefix),
    );
    if (!match) return;

    setSelectedPath(match.path);
    scrollEntryIntoView(match.path);
  };

  const scrollEntryIntoView = (entryPath: string) => {
    window.requestAnimationFrame(() => {
      dialogRef.current
        ?.querySelector<HTMLElement>(
          `[data-workspace-path="${CSS.escape(entryPath)}"]`,
        )
        ?.scrollIntoView({ block: "nearest" });
    });
  };

  const moveSelection = (direction: -1 | 1) => {
    if (selectableEntries.length === 0) return;
    typeaheadRef.current = { prefix: "", lastAt: 0 };

    const currentIndex = selectableEntries.findIndex(
      (entry) => entry.path === selectedPath,
    );
    let nextIndex = 0;
    if (currentIndex === -1) {
      nextIndex = direction > 0 ? 0 : selectableEntries.length - 1;
    } else {
      nextIndex = clamp(
        currentIndex + direction,
        0,
        selectableEntries.length - 1,
      );
    }

    const next = selectableEntries[nextIndex];
    setSelectedPath(next.path);
    scrollEntryIntoView(next.path);
  };

  const enterSelectedDirectory = () => {
    const selected = selectableEntries.find((entry) => entry.path === selectedPath);
    if (selected) {
      void loadDirectory(selected.path, showHidden, { focusList: true });
    }
  };

  const trapFocus = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (!isTextEntryTarget(event.target)) {
      if (event.key === "Enter") {
        event.preventDefault();
        void confirm();
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        moveSelection(-1);
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        moveSelection(1);
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        goParent();
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        enterSelectedDirectory();
        return;
      }
    }
    if (
      event.key.length === 1 &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.altKey &&
      !isTextEntryTarget(event.target)
    ) {
      event.preventDefault();
      selectByPrefix(event.key);
      return;
    }
    if (event.key !== "Tab" || !dialogRef.current) return;

    const focusable = Array.from(
      dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), [tabindex]:not([tabindex="-1"])',
      ),
    );
    if (focusable.length === 0) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const goParent = () => {
    if (parent) void loadDirectory(parent, showHidden, { focusList: true });
  };

  const confirm = async () => {
    const target = selectedPath || path;
    if (!target || busy) return;
    await onSelect(target);
  };

  const handleEntryKey = (
    event: React.KeyboardEvent<HTMLDivElement>,
    entry: WorkspaceEntry,
  ) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void confirm();
    } else if (event.key === " ") {
      event.preventDefault();
      if (entry.kind === "directory" && entry.readable) {
        setSelectedPath(entry.path);
        focusList();
      }
    }
  };

  return (
    <div
      className="workspace-picker-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div
        className="workspace-picker"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Choose workspace folder"
        onKeyDown={trapFocus}
        style={
          position
            ? {
                left: `${position.left}px`,
                top: `${position.top}px`,
              }
            : { visibility: "hidden" }
        }
      >
        <div className="workspace-picker-header" onPointerDown={startDrag}>
          <div>
            <div className="workspace-picker-title">Choose Workspace</div>
            <div className="workspace-picker-subtitle">
              Select a directory for sessions and tools.
            </div>
          </div>
          <button
            className="workspace-picker-icon-btn"
            type="button"
            onClick={close}
            disabled={busy}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <form
          className="workspace-picker-pathbar"
          onSubmit={(event) => {
            event.preventDefault();
            void loadDirectory(inputPath);
          }}
        >
          <input
            ref={inputRef}
            value={inputPath}
            onChange={(event) => setInputPath(event.target.value)}
            spellCheck={false}
            aria-label="Directory path"
          />
          <button type="submit" disabled={loading || !inputPath.trim()}>
            Go
          </button>
        </form>

        <div className="workspace-picker-toolbar">
          <button
            className="workspace-picker-toolbar-icon-btn"
            type="button"
            onClick={goParent}
            disabled={!parent || loading}
            title="Up"
            aria-label="Up"
          >
            <Icon name="chevron-up" size={16} />
          </button>
          <button
            type="button"
            onClick={() => home && void loadDirectory(home)}
            disabled={!home || loading}
          >
            Home
          </button>
          {roots.map((root) => (
            <button
              key={root}
              type="button"
              onClick={() => void loadDirectory(root)}
              disabled={loading}
            >
              {root}
            </button>
          ))}
          <button
            type="button"
            onClick={() => void loadDirectory(path)}
            disabled={loading}
          >
            Refresh
          </button>
          <label className="workspace-picker-hidden-toggle">
            <input
              type="checkbox"
              checked={showHidden}
              onChange={(event) => {
                const checked = event.target.checked;
                setShowHidden(checked);
                void loadDirectory(path, checked);
              }}
            />
            Show Hidden
          </label>
        </div>

        {error && <div className="workspace-picker-error">{error}</div>}

        <div
          className="workspace-picker-list"
          ref={listRef}
          tabIndex={-1}
          aria-busy={loading}
        >
          {parent && (
            <div
              className="workspace-picker-row workspace-picker-row--parent"
              role="button"
              tabIndex={0}
              onClick={goParent}
              onKeyDown={(event) => {
                if (event.key === "Enter") goParent();
              }}
            >
              <span className="workspace-picker-kind workspace-picker-kind--parent">
                ..
              </span>
              <span className="workspace-picker-name">..</span>
              <span className="workspace-picker-meta">Parent</span>
              <span />
            </div>
          )}
          {entries.map((entry) => {
            const selectable = entry.kind === "directory" && entry.readable;
            return (
              <div
                key={entry.path}
                className={`workspace-picker-row ${
                  selectedPath === entry.path ? "is-selected" : ""
                } ${!selectable ? "is-muted" : ""}`}
                role="button"
                tabIndex={selectable ? 0 : -1}
                title={entry.path}
                data-workspace-path={entry.path}
                onClick={() => {
                  if (selectable) {
                    setSelectedPath(entry.path);
                    focusList();
                  }
                }}
                onDoubleClick={() => {
                  if (selectable) {
                    void loadDirectory(entry.path, showHidden, {
                      focusList: true,
                    });
                  }
                }}
                onKeyDown={(event) => handleEntryKey(event, entry)}
              >
                <span className="workspace-picker-kind">
                  <Icon name={iconForEntry(entry)} size={17} />
                </span>
                <span className="workspace-picker-name">{entry.name}</span>
                <span className="workspace-picker-meta">
                  {entry.kind === "directory"
                    ? entry.readable
                      ? "Folder"
                      : "Blocked"
                    : formatSize(entry.size)}
                </span>
                <span className="workspace-picker-meta">
                  {formatModified(entry.modified_at)}
                </span>
              </div>
            );
          })}
          {!loading && entries.length === 0 && (
            <div className="workspace-picker-empty">No visible entries</div>
          )}
          {loading && <div className="workspace-picker-loading">Loading...</div>}
        </div>

        <div className="workspace-picker-footer">
          <div className="workspace-picker-selected" title={selectedPath || path}>
            {selectedPath || path}
          </div>
          <button type="button" onClick={close} disabled={busy}>
            Cancel
          </button>
          <button
            className="workspace-picker-primary"
            type="button"
            onClick={() => void confirm()}
            disabled={busy || loading || !(selectedPath || path)}
          >
            {busy ? "Switching..." : "Use Folder"}
          </button>
        </div>
      </div>
    </div>
  );
}
