import { useState, useEffect } from "react";
import "./App.css";

function App() {
  const [backendMessage, setBackendMessage] = useState("Loading...");

  useEffect(() => {
    fetch("/api/hello")
      .then((res) => res.json())
      .then((data) => setBackendMessage(data.message))
      .catch(() => setBackendMessage("Failed to connect to backend"));
  }, []);

  return (
    <div className="app">
      <h1>Hello World from React!</h1>
      <p>
        Backend says: <strong>{backendMessage}</strong>
      </p>
    </div>
  );
}

export default App;
