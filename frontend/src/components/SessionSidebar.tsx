import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import Icon from "./Icon";
import WorkspacePickerModal from "./WorkspacePickerModal";
import type { SessionInfo } from "../types";

interface SessionSidebarProps {
  activeId: string | null;
  workspace: string;
  onWorkspaceChange: (workspace: string) => void;
  onSelect: (sid: string) => void;
  onNew: () => void;
  onDelete?: (sid: string) => void;
  onOpenSettings: () => void;
  onOpenMetrics: () => void;
}

function workspaceLabel(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  const parts = normalized.split("/").filter(Boolean);
  return parts[parts.length - 1] || path;
}

export default function SessionSidebar({
  activeId,
  workspace,
  onWorkspaceChange,
  onSelect,
  onNew,
  onDelete,
  onOpenSettings,
  onOpenMetrics,
}: SessionSidebarProps) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [activatingId, setActivatingId] = useState<string | null>(null);
  const workspaceLoadedRef = useRef(false);
  const [menuSid, setMenuSid] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const sidebarRef = useRef<HTMLDivElement | null>(null);

  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch("/api/sessions/all");
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data: {
        workspace?: string;
        sessions: Array<SessionInfo | string>;
      } = await res.json();
      setSessions(
        (data.sessions || [])
          .map((item) =>
            typeof item === "string"
              ? { session_id: item, workspace: data.workspace || "" }
              : item,
          )
          .filter((session) => session.session_kind !== "subagent"),
      );
      setError(null);
    } catch (err) {
      setSessions([]);
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const groupedSessions = useMemo(() => {
    const groups = new Map<string, SessionInfo[]>();
    for (const session of sessions) {
      const key = session.workspace || workspace || "unknown";
      const bucket = groups.get(key);
      if (bucket) {
        bucket.push(session);
      } else {
        groups.set(key, [session]);
      }
    }
    return Array.from(groups.entries()).sort(([a], [b]) => {
      if (a === workspace) return -1;
      if (b === workspace) return 1;
      return a.localeCompare(b);
    });
  }, [sessions, workspace]);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions, activeId, workspace]);

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

  const applyWorkspace = async (path: string) => {
    setSelecting(true);
    try {
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
      await fetchSessions();
      setPickerOpen(false);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSelecting(false);
    }
  };

  const activateSession = async (session: SessionInfo) => {
    const targetWorkspace = session.workspace;
    if (!targetWorkspace) {
      onSelect(session.session_id);
      return;
    }

    setActivatingId(session.session_id);
    try {
      if (targetWorkspace !== workspace) {
        const res = await fetch("/api/workspace/set", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: targetWorkspace }),
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
      }
      onSelect(session.session_id);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActivatingId(null);
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
          onClick={() => setPickerOpen(true)}
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
        {groupedSessions.map(([wsPath, groupSessions]) => (
          <div key={wsPath} className="sidebar-group">
            <div
              className={`sidebar-group-label ${wsPath === workspace ? "sidebar-group-label--current" : ""}`}
              title={wsPath}
            >
              {workspaceLabel(wsPath)}
              {wsPath === workspace ? " (current)" : ""}
            </div>
            {groupSessions.map((session) => {
              const label = session.session_name || session.session_id;
              const isActive = session.session_id === activeId;
              const isMenuOpen = session.session_id === menuSid;
              const isDeleting = session.session_id === deleting;
              const isActivating = session.session_id === activatingId;

              return (
                <div
                  key={`${session.workspace}:${session.session_id}`}
                  className={`sidebar-item ${isActive ? "active" : ""}`}
                  onClick={() => void activateSession(session)}
                >
                  <span className="sidebar-item-dot" />
                  <span className="sidebar-item-text">
                    <span className="sidebar-item-title">{label}</span>
                    <span className="sidebar-item-id">
                      {session.session_id}
                    </span>
                  </span>

                  <div className="sidebar-item-actions">
                    <button
                      className="sidebar-menu-btn"
                      title="Session actions"
                      disabled={isDeleting || isActivating}
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
                            void handleDelete(session.session_id);
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
        ))}
      </div>
      <div className="sidebar-footer">
        <button
          className="sidebar-settings-btn"
          type="button"
          onClick={onOpenMetrics}
          title="Metrics"
        >
          <Icon name="chart" size={17} />
          <span>Metrics</span>
        </button>
        <button
          className="sidebar-settings-btn"
          type="button"
          onClick={onOpenSettings}
          title="Settings"
        >
          <Icon name="settings" size={17} />
          <span>Settings</span>
        </button>
      </div>
      {pickerOpen && (
        <WorkspacePickerModal
          initialPath={workspace}
          busy={selecting}
          onClose={() => setPickerOpen(false)}
          onSelect={applyWorkspace}
        />
      )}
    </div>
  );
}
