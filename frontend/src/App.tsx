import { useState, useCallback } from "react";
import AgentDemo from "./components/AgentDemo";
import SessionSidebar from "./components/SessionSidebar";
import SettingsWindow from "./components/SettingsWindow";
import "./App.css";


export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);

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
        onOpenSettings={() => setSettingsOpen(true)}
      />
      <div className="app-main">
        <AgentDemo
          sessionId={sessionId}
          onSessionCreated={handleSessionCreated}
        />
      </div>
      {settingsOpen && (
        <SettingsWindow
          workspace={workspace}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  );
}
