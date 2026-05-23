import { useState, useCallback, useRef } from "react";
import AgentDemo from "./components/AgentDemo";
import SessionSidebar from "./components/SessionSidebar";
import type { SessionCache } from "./types";
import "./App.css";

// Per-session state cache (survives component switches without remounting)
const sessionCache: SessionCache = {};

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [pendingNew, setPendingNew] = useState(false);
  const [workspace, setWorkspace] = useState("");
  const cacheRef = useRef<SessionCache>(sessionCache);

  const handleSelect = useCallback((sid: string) => {
    setSessionId(sid);
    setPendingNew(false);
  }, []);

  const handleNew = useCallback(() => {
    setSessionId(null);
    setPendingNew(true);
  }, []);

  const handleWorkspaceChange = useCallback((nextWorkspace: string) => {
    setWorkspace(nextWorkspace);
    setSessionId(null);
    setPendingNew(false);
  }, []);

  const handleSessionCreated = useCallback((sid: string, resolvedWorkspace?: string) => {
    if (resolvedWorkspace) setWorkspace(resolvedWorkspace);
    setSessionId(sid);
  }, []);

  return (
    <div className="app-layout">
      <SessionSidebar
        activeId={sessionId}
        workspace={workspace}
        onWorkspaceChange={handleWorkspaceChange}
        onWorkspaceResolved={setWorkspace}
        onSelect={handleSelect}
        onNew={handleNew}
      />
      <div className="app-main">
        {sessionId || pendingNew ? (
          <AgentDemo
            sessionId={sessionId}
            pendingNew={pendingNew}
            workspace={workspace}
            onSessionCreated={handleSessionCreated}
            cache={cacheRef.current}
          />
        ) : (
          <div className="app-placeholder">
            Select a session or create a new one.
          </div>
        )}
      </div>
    </div>
  );
}
