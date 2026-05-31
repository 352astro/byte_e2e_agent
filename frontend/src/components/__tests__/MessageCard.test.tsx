import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import MessageCard from "../MessageCard";
import type { Message, ToolCall } from "../../types";

// Mock sub-components to isolate MessageCard logic
vi.mock("../Markdown", () => ({
  default: ({ text }: { text: string }) => (
    <span data-testid="markdown">{text}</span>
  ),
}));
vi.mock("../Icon", () => ({
  default: ({ name }: { name: string }) => (
    <span data-testid={`icon-${name}`} />
  ),
}));
vi.mock("../CollapsibleCard", () => ({
  default: ({
    children,
    title,
  }: {
    children: React.ReactNode;
    title: React.ReactNode;
  }) => (
    <div data-testid="collapsible">
      {title}
      {children}
    </div>
  ),
}));
vi.mock("../ToolResult", () => ({
  default: ({ toolName, result }: { toolName: string; result: string }) => (
    <div data-testid="tool-result">
      <span data-testid="tool-name">{toolName}</span>
      <span data-testid="tool-result-text">{result}</span>
    </div>
  ),
}));
vi.mock("../ToolCards", () => ({
  renderToolCard: (props: { id: string; toolName: string; args: string }) => (
    <div data-testid="tool-card">
      <span data-testid="tc-name">{props.toolName}</span>
      <span data-testid="tc-args">{props.args}</span>
    </div>
  ),
}));
vi.mock("../../hooks/FocusContext", () => ({
  useFocusedId: () => undefined,
}));

// ── helpers ──────────────────────────────────────────────

function makeMsg(overrides: Partial<Message> = {}): Message {
  return {
    id: "m1",
    turn_id: "t1",
    role: "assistant",
    status: "complete",
    content: "",
    reasoning: "",
    tool_calls: [],
    tool_result: "",
    tool_call_id: "",
    tool_name: "",
    error: "",
    ...overrides,
  } as Message;
}

// ═══════════════════════════════════════════════════════════

describe("MessageCard", () => {
  // ── User ────────────────────────────────────────────

  it("renders user message as user-bubble", () => {
    render(
      <MessageCard
        message={makeMsg({ role: "user", content: "hello world" })}
      />,
    );
    const bubble = document.querySelector(".user-bubble");
    expect(bubble).not.toBeNull();
    expect(bubble!.textContent).toContain("hello world");
  });

  it("user bubble shows 'You' label", () => {
    render(<MessageCard message={makeMsg({ role: "user", content: "hi" })} />);
    expect(screen.getByText("You")).not.toBeNull();
  });

  // ── Assistant ───────────────────────────────────────

  it("renders assistant content via Markdown", () => {
    render(
      <MessageCard
        message={makeMsg({ role: "assistant", content: "# Title" })}
      />,
    );
    expect(screen.getByTestId("markdown")).not.toBeNull();
    expect(screen.getByTestId("markdown").textContent).toBe("# Title");
  });

  it("renders reasoning block when reasoning is present", () => {
    render(
      <MessageCard
        message={makeMsg({ role: "assistant", reasoning: "thinking..." })}
      />,
    );
    expect(screen.getByTestId("collapsible")).not.toBeNull();
    expect(screen.getByTestId("icon-bulb")).not.toBeNull();
  });

  it("does not render reasoning block when empty", () => {
    render(
      <MessageCard message={makeMsg({ role: "assistant", reasoning: "" })} />,
    );
    expect(screen.queryByTestId("icon-bulb")).toBeNull();
  });

  it("streaming assistant shows 'thinking...' when empty", () => {
    render(
      <MessageCard
        message={makeMsg({
          role: "assistant",
          status: "streaming",
          content: "",
          reasoning: "",
        })}
      />,
    );
    expect(screen.getAllByText("thinking...").length).toBeGreaterThan(0);
  });

  // ── Tool ────────────────────────────────────────────

  it("renders tool message via ToolResult", () => {
    render(
      <MessageCard
        message={makeMsg({
          role: "tool",
          tool_name: "Shell",
          tool_result: "command output",
        })}
      />,
    );
    expect(screen.getByTestId("tool-result")).not.toBeNull();
    expect(screen.getByTestId("tool-name").textContent).toBe("Shell");
    expect(screen.getByTestId("tool-result-text").textContent).toBe(
      "command output",
    );
  });

  // ── Error ───────────────────────────────────────────

  it("renders error message in error card", () => {
    render(
      <MessageCard
        message={makeMsg({ role: "assistant", error: "something went wrong" })}
      />,
    );
    expect(document.querySelector(".error-card")).not.toBeNull();
    expect(screen.getByText("something went wrong")).not.toBeNull();
    expect(screen.getByTestId("icon-error")).not.toBeNull();
  });

  // ── Tool calls ──────────────────────────────────────

  it("renders tool calls when present", () => {
    const tc: ToolCall = {
      id: "tc1",
      type: "function",
      function: { name: "Shell", arguments: '{"cmd":"ls"}' },
    } as ToolCall;

    render(
      <MessageCard
        message={makeMsg({ role: "assistant", tool_calls: [tc] })}
      />,
    );

    expect(screen.getByTestId("tool-card")).not.toBeNull();
    expect(screen.getByTestId("tc-name").textContent).toBe("Shell");
  });

  it("hides tool cards when hideToolCards is true", () => {
    const tc: ToolCall = {
      id: "tc1",
      type: "function",
      function: { name: "Shell", arguments: "{}" },
    } as ToolCall;

    render(
      <MessageCard
        message={makeMsg({ role: "assistant", tool_calls: [tc] })}
        hideToolCards
      />,
    );

    expect(screen.queryByTestId("tool-card")).toBeNull();
  });

  // ── Tool call without function ──────────────────────

  it("renders tool call with fallback name when function missing", () => {
    render(
      <MessageCard
        message={makeMsg({
          role: "assistant",
          tool_calls: [{ id: "tc1", type: "function" } as ToolCall],
        })}
      />,
    );

    expect(screen.getByTestId("tc-name").textContent).toBe("unknown");
  });
});
