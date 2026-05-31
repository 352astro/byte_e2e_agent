import { useState, useCallback, useRef } from "react";
import AgentDemo from "./components/AgentDemo";
import SessionSidebar from "./components/SessionSidebar";
import type { SessionCache } from "./types";
import "./App.css";

const sessionCache: SessionCache = {};

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState("");
  const cacheRef = useRef<SessionCache>(sessionCache);

  const handleSelect = useCallback((sid: string) => {
    setSessionId(sid);
  }, []);

  const handleNew = useCallback(() => {
    setSessionId(null);
  }, []);

  const handleDelete = useCallback(
    (sid: string) => {
      if (sessionId === sid) {
        setSessionId(null);
      }
    },
    [sessionId],
  );

  const handleSessionCreated = useCallback((sid: string) => {
    setSessionId(sid);
  }, []);

  const handleWorkspaceChange = useCallback((nextWorkspace: string) => {
    setWorkspace(nextWorkspace);
    setSessionId(null);
  }, []);

  return (
    <div className="app-layout">
      <SessionSidebar
        activeId={sessionId}
        workspace={workspace}
        onWorkspaceChange={handleWorkspaceChange}
        onSelect={handleSelect}
        onNew={handleNew}
        onDelete={handleDelete}
      />
      <div className="app-main">
        <AgentDemo
          sessionId={sessionId}
          onSessionCreated={handleSessionCreated}
          cache={cacheRef.current}
        />
      </div>
    </div>
  );
}
