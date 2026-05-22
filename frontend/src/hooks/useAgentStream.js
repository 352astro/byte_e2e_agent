import { useState, useRef, useCallback } from "react";

export const RESULT_PREVIEW_LINES = 12;

export default function useAgentStream() {
  const [question, setQuestion] = useState("");
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState([]);
  const [answer, setAnswer] = useState(null);

  const currentStepRef = useRef(null);
  const reasoningRef = useRef("");
  const actionRef = useRef("");

  // ── helpers ──────────────────────────────────────

  const updateCurrentStep = useCallback((fn) => {
    setSteps((prev) => {
      const idx = prev.length - 1;
      if (idx < 0) return prev;
      const copy = [...prev];
      copy[idx] = fn(copy[idx]);
      return copy;
    });
  }, []);

  const finalizeStep = useCallback(() => {
    setSteps((prev) => {
      const idx = prev.length - 1;
      if (idx < 0) return prev;
      const copy = [...prev];
      copy[idx] = { ...copy[idx], open: false, actionFinal: true };
      return copy;
    });
  }, []);

  // ── event dispatcher ─────────────────────────────

  const dispatch = useCallback(
    (event) => {
      switch (event.type) {
        case "step_start": {
          if (currentStepRef.current !== null) finalizeStep();
          currentStepRef.current = event.step;
          reasoningRef.current = "";
          actionRef.current = "";
          setSteps((prev) => [
            ...prev,
            { step: event.step, reasoning: "", action: "", events: [], open: true },
          ]);
          break;
        }

        case "reasoning_token":
          reasoningRef.current += event.token;
          updateCurrentStep((s) => ({ ...s, reasoning: reasoningRef.current }));
          break;

        case "thought_token":
          actionRef.current += event.token;
          updateCurrentStep((s) => ({ ...s, action: actionRef.current }));
          break;

        case "thought_end":
          updateCurrentStep((s) => ({ ...s, actionFinal: true }));
          break;

        case "tool_call":
        case "tool_result":
        case "plan_rewrite":
        case "plan_advance":
        case "subtask_start":
        case "subtask_end":
          updateCurrentStep((s) => ({ ...s, events: [...s.events, event] }));
          break;

        case "terminal_chunk":
          updateCurrentStep((s) => {
            const events = [...s.events];
            const last = events[events.length - 1];
            if (last && last.type === "terminal_stream") {
              // Append to existing stream buffer
              events[events.length - 1] = {
                ...last,
                output: last.output + event.chunk,
              };
            } else {
              // Start new stream buffer
              events.push({ type: "terminal_stream", output: event.chunk });
            }
            return { ...s, events };
          });
          break;

        case "finish":
          // Keep last step expanded for review
          setAnswer(event.answer);
          break;

        case "error":
          updateCurrentStep((s) => ({ ...s, events: [...s.events, event] }));
          break;
      }
    },
    [updateCurrentStep, finalizeStep],
  );

  // ── run ──────────────────────────────────────────

  const handleRun = useCallback(async () => {
    if (!question.trim() || running) return;

    setRunning(true);
    setSteps([]);
    setAnswer(null);
    currentStepRef.current = null;
    reasoningRef.current = "";
    actionRef.current = "";

    try {
      const res = await fetch("/api/agent/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question.trim(), max_steps: 50 }),
      });

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop();

        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));
            dispatch(event);
          } catch {
            // ignore malformed SSE lines
          }
        }
      }
    } catch (err) {
      setAnswer(`Connection error: ${err.message}`);
    } finally {
      setRunning(false);
    }
  }, [question, running, dispatch]);

  // ── step UI actions ──────────────────────────────

  const toggleStep = useCallback((idx) => {
    setSteps((prev) => {
      const copy = [...prev];
      copy[idx] = { ...copy[idx], open: !copy[idx].open };
      return copy;
    });
  }, []);

  const expandResult = useCallback((idx, evIdx) => {
    setSteps((prev) => {
      const copy = [...prev];
      const evts = [...copy[idx].events];
      evts[evIdx] = { ...evts[evIdx], expanded: true };
      copy[idx] = { ...copy[idx], events: evts };
      return copy;
    });
  }, []);

  return {
    question,
    setQuestion,
    running,
    steps,
    answer,
    handleRun,
    toggleStep,
    expandResult,
  };
}
