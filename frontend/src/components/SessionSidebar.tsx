import { useState, useEffect, useRef, useCallback } from "react";
import type { SessionInfo } from "../types";

interface SessionSidebarProps {
  activeId: string | null;
  workspace: string;
  onWorkspaceChange: (workspace: string) => void;
  onSelect: (sid: string) => void;
  onNew: () => void;
  onDelete?: (sid: string) => void;
}

export default function SessionSidebar({
  activeId,
  workspace,
  onWorkspaceChange,
  onSelect,
  onNew,
  onDelete,
}: SessionSidebarProps) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selecting, setSelecting] = useState(false);
  const workspaceLoadedRef = useRef(false);
  const [menuSid, setMenuSid] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const sidebarRef = useRef<HTMLDivElement | null>(null);

  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch("/api/sessions");
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data: {
        workspace?: string;
        sessions: Array<SessionInfo | string>;
      } = await res.json();
      setSessions(
        (data.sessions || []).map((item) =>
          typeof item === "string"
            ? { session_id: item, workspace: data.workspace || "" }
            : item,
        ),
      );
      setError(null);
    } catch (err) {
      setSessions([]);
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions, activeId]);

  // Fetch current workspace on mount
  useEffect(() => {
    fetch("/api/workspace")
      .then((r) => r.json())
      .then((data: { workspace: string }) => {
        if (data.workspace && !workspaceLoadedRef.current) {
          workspaceLoadedRef.current = true;
          onWorkspaceChange(data.workspace);
        }
      })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Close context menu on outside click
  useEffect(() => {
    if (!menuSid) return;
    const close = (e: MouseEvent) => {
      if (
        sidebarRef.current &&
        !sidebarRef.current.contains(e.target as Node)
      ) {
        setMenuSid(null);
      }
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menuSid]);

  const chooseWorkspace = async () => {
    setSelecting(true);
    try {
      let selectedPath: string | null = null;
      try {
        const handle = await window.showDirectoryPicker({
          mode: "read",
          startIn: "documents",
        });
        const parent = workspace.split("/").slice(0, -1).join("/") || "/";
        selectedPath = `${parent}/${handle.name}`;
      } catch {
        // User cancelled — fall back to manual input
      }
      const path = window.prompt(
        "Workspace directory:",
        selectedPath || workspace || "",
      );
      if (!path || !path.trim()) {
        setError(null);
        return;
      }
      const res = await fetch("/api/workspace/set", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: path.trim() }),
      });
      if (!res.ok) {
        const detail = await res
          .json()
          .then((d) => d.detail)
          .catch(() => "Unknown error");
        throw new Error(detail);
      }
      const data: { workspace: string } = await res.json();
      onWorkspaceChange(data.workspace);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSelecting(false);
    }
  };

  const handleDelete = async (sid: string) => {
    setMenuSid(null);
    setDeleting(sid);
    try {
      const res = await fetch(`/api/session/${sid}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      if (activeId === sid && onDelete) {
        onDelete(sid);
      }
      await fetchSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="sidebar" ref={sidebarRef}>
      <div className="sidebar-workspace">
        <span>Workspace</span>
        <div className="sidebar-workspace-path">
          {workspace || "Loading workspace..."}
        </div>
        <button
          className="sidebar-workspace-btn"
          type="button"
          onClick={chooseWorkspace}
          disabled={selecting}
        >
          {selecting ? "Selecting..." : "Choose Folder"}
        </button>
      </div>
      <button className="sidebar-new-btn" onClick={onNew}>
        + New Session
      </button>
      {error && <div className="sidebar-error">{error}</div>}
      <div className="sidebar-list">
        {sessions.map((session) => {
          const label = session.session_name || session.session_id;
          const isActive = session.session_id === activeId;
          const isMenuOpen = session.session_id === menuSid;
          const isDeleting = session.session_id === deleting;

          return (
            <div
              key={session.session_id}
              className={`sidebar-item ${isActive ? "active" : ""}`}
              onClick={() => onSelect(session.session_id)}
            >
              <span className="sidebar-item-dot" />
              <span className="sidebar-item-text">
                <span className="sidebar-item-title">{label}</span>
                <span className="sidebar-item-id">{session.session_id}</span>
              </span>

              {/* three-dot menu */}
              <div className="sidebar-item-actions">
                <button
                  className="sidebar-menu-btn"
                  title="Session actions"
                  disabled={isDeleting}
                  onClick={(e) => {
                    e.stopPropagation();
                    setMenuSid(isMenuOpen ? null : session.session_id);
                  }}
                >
                  ⋮
                </button>

                {isMenuOpen && (
                  <div className="sidebar-context-menu">
                    <button
                      className="sidebar-context-item sidebar-context-item--danger"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(session.session_id);
                      }}
                    >
                      Delete
                    </button>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
