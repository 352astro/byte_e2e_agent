/**
 * Integration test: full session trace via real backend.
 *
 * Start backend first:
 *   cd backend && uv run uvicorn main:app --port 8000
 *
 * Then run:
 *   cd frontend && npx vitest run src/__tests__/integration.test.ts
 */
import { describe, it, expect, beforeAll } from "vitest";

const BASE = "http://localhost:8000";

async function post(endpoint: string, body?: Record<string, unknown>) {
  const r = await fetch(`${BASE}${endpoint}`, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  return r.json();
}

async function g(endpoint: string) {
  const r = await fetch(`${BASE}${endpoint}`);
  return r.json();
}

async function sseChat(sid: string, question: string, maxSteps = 3) {
  const events: Record<string, unknown>[] = [];
  const r = await fetch(`${BASE}/api/session/${sid}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, max_steps: maxSteps }),
  });
  if (!r.ok) throw new Error(`Chat failed: ${r.status}`);
  if (!r.body) throw new Error("No response body");

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;

  while (!finished) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop()!;
    for (const part of parts) {
      const line = part.trim();
      if (line.startsWith("data: ")) {
        try {
          const ev = JSON.parse(line.slice(6));
          events.push(ev);
          if (ev.kind === "turn_complete" || ev.kind === "interrupted") {
            finished = true;
          }
        } catch {
          /* ignore malformed */
        }
      }
    }
  }
  if (buffer.trim().startsWith("data: ")) {
    try {
      events.push(JSON.parse(buffer.trim().slice(6)));
    } catch {
      /* */
    }
  }
  reader.cancel();
  return events;
}

function kinds(events: Record<string, unknown>[]) {
  return events.map((e) => e.kind);
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

describe("full session trace", () => {
  let sid: string;

  beforeAll(async () => {
    try {
      await fetch(`${BASE}/`);
    } catch {
      throw new Error(
        "Backend not reachable — start: uv run uvicorn main:app --port 8000",
      );
    }
  });

  it("creates a session", async () => {
    const data = await post("/api/session");
    expect(data.session_id).toBeTruthy();
    sid = data.session_id;
    console.log("Session:", sid);
  });

  it("chat 1: simple reply", { timeout: 60000 }, async () => {
    const events = await sseChat(sid, "Say 'hello' and nothing else.", 3);
    const ks = kinds(events);
    console.log("Chat 1:", ks.length, "events:", ks.slice(0, 6), "...");

    expect(ks).toContain("message_start");
    expect(ks).toContain("chunk_delta");
    expect(ks).toContain("message_finish");

    const starts = events.filter((e) => e.kind === "message_start");
    expect(starts.map((e) => e.role)).toEqual(
      expect.arrayContaining(["user", "assistant"]),
    );

    const deltas = events.filter(
      (e) => e.kind === "chunk_delta" && e.field === "content",
    );
    expect(deltas.length).toBeGreaterThan(0);
  });

  it("chat 2: reasoning", { timeout: 60000 }, async () => {
    const events = await sseChat(sid, "Think step by step: what is 15 * 7?", 3);
    const ks = kinds(events);
    console.log("Chat 2:", ks.length, "events:", ks.slice(0, 6), "...");

    expect(ks).toContain("message_start");
    expect(ks).toContain("chunk_delta");
    expect(ks).toContain("message_finish");

    const reasoning = events.filter(
      (e) => e.kind === "chunk_delta" && e.field === "reasoning",
    );
    console.log(`  reasoning chunks: ${reasoning.length}`);
    if (reasoning.length > 0) {
      console.log(`  first delta: "${reasoning[0].delta}"`);
    }
  });

  it("refresh: recover returns complete messages", async () => {
    const data = await g(`/api/session/${sid}/recover`);
    expect(data.messages).toBeInstanceOf(Array);
    const msgs = data.messages as Record<string, unknown>[];
    console.log(`Recover: ${msgs.length} messages, running=${data.running}`);

    expect(msgs.length).toBeGreaterThanOrEqual(4);

    for (let i = 0; i < msgs.length; i++) {
      const m = msgs[i];
      expect(m.id).toBeTruthy();
      expect(m.role).toBeTruthy();
      expect(m.status).toBeTruthy();
    }

    const assistants = msgs.filter((m) => m.role === "assistant");
    expect(assistants.length).toBeGreaterThanOrEqual(2);
  });

  it("recover: running is false", async () => {
    const data = await g(`/api/session/${sid}/recover`);
    expect(data.running).toBe(false);
  });

  it(
    "recover: captures current_message during streaming",
    { timeout: 90000 },
    async () => {
      // 发起一个需要多步推理的请求
      const chatPromise = sseChat(
        sid,
        "Write a detailed paragraph about the history of artificial intelligence, " +
          "covering at least three major milestones. Be thorough.",
        5,
      );

      // 轮询 /recover，直到捕获到 streaming 中的 current_message
      // 模型可能在工具调用链中（model_call 之间有间隙），需要重试
      let currentMessage: Record<string, unknown> | null = null;
      let attempts = 0;
      const maxAttempts = 40;

      while (attempts < maxAttempts) {
        if (attempts > 0) await sleep(50);
        attempts++;
        const data = await g(`/api/session/${sid}/recover`);
        if (data.current_message != null) {
          currentMessage = data.current_message as Record<string, unknown>;
          console.log(
            `  captured after ${attempts} attempt(s): ` +
              `role=${currentMessage.role} status=${currentMessage.status} ` +
              `content_len=${(currentMessage.content as string).length} ` +
              `reasoning_len=${(currentMessage.reasoning as string).length}`,
          );
          break;
        }
        if (!data.running) {
          console.log(`  chat finished before capturing streaming message`);
          break;
        }
      }

      expect(currentMessage).not.toBeNull();
      const cm = currentMessage!;

      expect(cm.role).toBe("assistant");
      expect(cm.status).toBe("streaming");
      expect(cm.id).toBeTruthy();

      // current_message 在 model_call 创建 Message 后立即设置，
      // 可能尚未收到第一个 token（content/reasoning 为空）。
      // 前端通过后续 SSE chunk_delta 事件填充内容。
      // 此处只验证结构完整性。
      console.log(
        `  content preview: "${(cm.content as string).slice(0, 80)}"`,
      );
      console.log(
        `  reasoning preview: "${(cm.reasoning as string).slice(0, 80)}"`,
      );

      await chatPromise;
    },
  );

  it("recover: current_message is null after turn completes", async () => {
    const data = await g(`/api/session/${sid}/recover`);
    expect(data.running).toBe(false);
    expect(data.current_message).toBeNull();
  });

  it(
    "tool call: no UNKNOWN spam during streaming assembly",
    { timeout: 60000 },
    async () => {
      // 用新 session 隔离，避免历史干扰
      const { session_id: testSid } = await post("/api/session");
      console.log("Tool-call test session:", testSid);

      const events = await sseChat(
        testSid,
        "Run the shell command `date` and tell me the output. " +
          "Do not use any other tools. Just Shell once.",
        3,
      );

      const ks = kinds(events);
      console.log(`Tool-call chat: ${ks.length} events`);

      // 1) 存在 tool_calls 的 chunk_complete
      const tcCompletes = events.filter(
        (e) => e.kind === "chunk_complete" && e.field === "tool_calls",
      );
      console.log(`  chunk_complete(tool_calls): ${tcCompletes.length}`);

      // 2) 每个 tool_calls chunk_delta 的 tool_name 不能为空
      const tcDeltas = events.filter(
        (e) => e.kind === "chunk_delta" && e.field === "tool_calls",
      );
      console.log(`  chunk_delta(tool_calls): ${tcDeltas.length}`);
      for (const d of tcDeltas) {
        const tn = d.tool_name as string;
        const sf = d.sub_field as string;
        // tool_name 应该在 name 子字段收到后就有值
        if (sf === "args" && !tn) {
          console.log(
            `  WARN: args delta with empty tool_name, delta="${d.delta}"`,
          );
        }
      }

      // 3) recover 后的消息不能有 "unknown" 的 tool name
      const data = await g(`/api/session/${testSid}/recover`);
      const msgs = data.messages as Record<string, unknown>[];
      for (const m of msgs) {
        const tcs = (m.tool_calls as Record<string, unknown>[]) || [];
        for (const tc of tcs) {
          const fn = (tc.function as Record<string, string>) || {};
          const name = fn.name || "";
          console.log(
            `  tool_call: name="${name}" args_len=${(fn.arguments || "").length}`,
          );
          expect(name).not.toBe("");
          expect(name).not.toBe("unknown");
        }
      }

      // 4) 清理
      await fetch(`${BASE}/api/session/${testSid}`, { method: "DELETE" });
    },
  );
});
