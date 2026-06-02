import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import useAgentStream from "../useAgentStream";

// ═══════════════════════════════════════════════════════════

describe("useAgentStream", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          session: {},
          messages: [],
          session_running: false,
          runtime_busy: false,
        }),
    } as Response);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── initial state ───────────────────────────────────

  it("initializes with empty messages and not running", () => {
    const { result } = renderHook(() =>
      useAgentStream({ sessionId: "sid1", cache: {} }),
    );

    expect(result.current.running).toBe(false);
    expect(result.current.interrupting).toBe(false);
    expect(result.current.messages).toEqual([]);
  });

  // ── resetRunning ───────────────────────────────────

  it("resetRunning sets running and interrupting to false", () => {
    const { result } = renderHook(() =>
      useAgentStream({ sessionId: "sid1", cache: {} }),
    );

    act(() => {
      result.current.resetRunning();
    });

    expect(result.current.running).toBe(false);
    expect(result.current.interrupting).toBe(false);
  });

  // ── truncateMessages ────────────────────────────────

  it("truncateMessages with empty messages does nothing", () => {
    const { result } = renderHook(() =>
      useAgentStream({ sessionId: null, cache: {} }),
    );

    act(() => {
      result.current.truncateMessages("any-id", false);
    });

    expect(result.current.messages).toEqual([]);
  });

  it("truncateMessages with null sessionId is a no-op", () => {
    const { result } = renderHook(() =>
      useAgentStream({ sessionId: null, cache: {} }),
    );

    // Should not throw
    act(() => {
      result.current.truncateMessages("any-id", true);
    });

    expect(result.current.messages).toEqual([]);
  });

  // ── scrollToMessage ────────────────────────────────

  it("scrollToMessage does not throw without container", () => {
    const { result } = renderHook(() =>
      useAgentStream({ sessionId: "sid1", cache: {} }),
    );

    expect(() => {
      result.current.scrollToMessage("some-id");
    }).not.toThrow();
  });

  // ── prefillRef ─────────────────────────────────────

  it("prefillRef starts as empty string", () => {
    const { result } = renderHook(() =>
      useAgentStream({ sessionId: "sid1", cache: {} }),
    );

    expect(result.current.prefillRef.current).toBe("");
  });

  // ── reloadMessages with null sessionId ──────────────

  it("reloadMessages with null sessionId resolves immediately", async () => {
    const { result } = renderHook(() =>
      useAgentStream({ sessionId: null, cache: {} }),
    );

    // Should not throw or hang
    await act(async () => {
      await result.current.reloadMessages();
    });

    expect(result.current.messages).toEqual([]);
  });

  // ── interrupt when not running ─────────────────────

  it("interrupt with null sessionId does nothing", async () => {
    const { result } = renderHook(() =>
      useAgentStream({ sessionId: null, cache: {} }),
    );

    await act(async () => {
      await result.current.interrupt();
    });

    expect(result.current.interrupting).toBe(false);
  });
});
