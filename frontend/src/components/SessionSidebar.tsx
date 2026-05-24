import { useState, useEffect } from "react";
import type { SessionInfo } from "../types";

interface SessionSidebarProps {
  activeId: string | null;
  workspace: string;
  onWorkspaceChange: (workspace: string) => void;
  onWorkspaceResolved: (workspace: string) => void;
  onSelect: (sid: string) => void;
  onNew: () => void;
}

export default function SessionSidebar({
  activeId,
  workspace,
  onWorkspaceChange,
  onWorkspaceResolved,
  onSelect,
  onNew,
}: SessionSidebarProps) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selecting, setSelecting] = useState(false);

  const fetchSessions = async () => {
    try {
      const query = workspace.trim()
        ? `?workspace=${encodeURIComponent(workspace.trim())}`
        : "";
      const res = await fetch(`/api/sessions${query}`);
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data: {
        workspace?: string;
        sessions: Array<SessionInfo | string>;
      } = await res.json();
      if (data.workspace) onWorkspaceResolved(data.workspace);
      setSessions(
        (data.sessions || []).map((item) =>
          typeof item === "string"
            ? { session_id: item, workspace: data.workspace || workspace }
            : item,
        ),
      );
      setError(null);
    } catch (err) {
      setSessions([]);
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    fetchSessions();
  }, [activeId, workspace]); // eslint-disable-line react-hooks/exhaustive-deps

  const chooseWorkspace = async () => {
    setSelecting(true);
    try {
      // Open native folder picker via File System Access API
      let selectedPath: string | null = null;

      try {
        const handle = await window.showDirectoryPicker({
          mode: "read",
          startIn: "documents",
        });
        // Build a path hint: parent of current workspace + picked folder name
        const parent = workspace.split("/").slice(0, -1).join("/") || "/";
        selectedPath = `${parent}/${handle.name}`;
      } catch {
        // User cancelled — fall back to manual input
      }

      // Let the user confirm / edit the path
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

  return (
    <div className="sidebar">
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
          return (
            <div
              key={session.session_id}
              className={`sidebar-item ${
                session.session_id === activeId ? "active" : ""
              }`}
              onClick={() => onSelect(session.session_id)}
            >
              <span className="sidebar-item-dot" />
              <span className="sidebar-item-text">
                <span className="sidebar-item-title">{label}</span>
                <span className="sidebar-item-id">{session.session_id}</span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
