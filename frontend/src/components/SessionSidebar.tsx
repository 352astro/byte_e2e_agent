import { useState, useEffect } from "react";

interface SessionSidebarProps {
  activeId: string | null;
  onSelect: (sid: string) => void;
  onNew: () => void;
}

export default function SessionSidebar({
  activeId,
  onSelect,
  onNew,
}: SessionSidebarProps) {
  const [sessions, setSessions] = useState<string[]>([]);

  const fetchSessions = async () => {
    try {
      const res = await fetch("/api/sessions");
      const data: { sessions: string[] } = await res.json();
      setSessions(data.sessions || []);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    fetchSessions();
  }, [activeId]);

  return (
    <div className="sidebar">
      <button className="sidebar-new-btn" onClick={onNew}>
        + New Session
      </button>
      <div className="sidebar-list">
        {sessions.map((sid) => (
          <div
            key={sid}
            className={`sidebar-item ${sid === activeId ? "active" : ""}`}
            onClick={() => onSelect(sid)}
          >
            <span className="sidebar-item-dot" />
            <span className="sidebar-item-id">{sid}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
