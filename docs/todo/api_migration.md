# API Migration — 前后端类型同步 + SSE 协议迁移

## 目标

用 FastAPI OpenAPI schema 自动生成前端 TypeScript 类型，消除 `types.ts` 手动同步；同时将前端 SSE 消费者从旧 `Transcript` 协议迁移到新 `Message` / `StreamEvent` 协议。

## 第一步：后端 — Pydantic Response Model

所有返回 `Message` 数据的路由目前返回裸 `dict`，导致 `/openapi.json` 不含 `Message` schema。

- [ ] `app/schemas/response.py` — 新增响应模型
  ```python
  class HistoryResponse(BaseModel):
      session: dict       # SessionInfo (暂用 dict)
      history: list[Message]

  class RecoverResponse(BaseModel):
      session: dict
      messages: list[Message]   # ← 旧名 transcripts
      running: bool = False

  class CreateSessionResponse(BaseModel):
      session_id: str

  class ListSessionsResponse(BaseModel):
      workspace: str
      sessions: list[dict]

  class StatusResponse(BaseModel):
      running: bool

  class CommitsResponse(BaseModel):
      commits: list[dict]
  ```

- [ ] `app/api/routes/sessions.py` — 挂载 `response_model`
  - `GET /session/{sid}/history` → `response_model=HistoryResponse`
  - `GET /session/{sid}/recover` → `response_model=RecoverResponse`
  - `POST /session` → `response_model=CreateSessionResponse`
  - `GET /sessions` → `response_model=ListSessionsResponse`
  - `GET /session/{sid}/status` → `response_model=StatusResponse`
  - `GET /session/{sid}/commits` → `response_model=CommitsResponse`

- [ ] 验证：`.venv/bin/python -c "from main import app; print(app.openapi()['components']['schemas'].keys())"` 输出含 `Message`, `ToolCall`, `ToolCallFunction`, `HistoryResponse` 等

- [ ] `app/api/routes/sessions.py` — 修 `/recover` 返回字段 `transcripts` → `messages`（前端迁移完毕后）

## 第二步：后端 — 补充缺失的 schema 暴露

部分类型不在路由响应中但前端需要（如 `StreamEvent` 用于 SSE）。

- [ ] `app/schemas/response.py` — 新增 SSE 事件模型（仅用于文档生成，非实际路由）
  ```python
  class StreamEventSchema(BaseModel):
      """SSE 事件（仅用于 OpenAPI 文档生成，实际不走 REST）"""
      kind: StreamEventKind
      message_id: str = ""
      turn_id: str = ""
      field: str = ""
      delta: str = ""
      full_content: str = ""
      tool_name: str = ""
      tool_args: str = ""
      is_error: bool = False
      input_tokens: int = 0
      output_tokens: int = 0
      reason: str = ""
  ```

- [ ] 将 `StreamEventSchema` 作为某个文档端点（如 `/api/sse-schema`）的 response_model，使其出现在 OpenAPI schema 中

## 第三步：前端 — 安装 openapi-typescript

- [ ] `cd frontend && npm install -D openapi-typescript`

- [ ] `frontend/package.json` — 添加脚本
  ```json
  {
    "scripts": {
      "gen-types": "openapi-typescript http://localhost:8000/openapi.json -o src/types.generated.ts"
    }
  }
  ```

- [ ] 验证：`npm run gen-types` 生成 `src/types.generated.ts`，包含 `Message`, `ToolCall`, `StreamEvent` 等接口

## 第四步：前端 — 重构类型层

- [ ] `src/types.ts` — 精简为只含手写部分
  - 删除 `Message`, `ToolCall`, `ToolCallFunction`, `MessageRole`, `MessageStatus`（从 generated 导入）
  - 保留前端专用类型：`SessionInfo`, `CommitInfo`, `CommitActions`, `CheckoutRequest`, `CheckoutResponse`, `getCommitActions`
  - 新增 `StreamEvent` 类型（SSE 不走 REST，需手写，保持与 `shared/types.py` 一致）

- [ ] `src/types.ts` — 重新导出
  ```typescript
  // 自动生成
  export type { Message, ToolCall, ToolCallFunction } from "./types.generated";
  export { MessageRole, MessageStatus } from "./types.generated";
  // 手写（SSE，前端专用）
  export type StreamEvent = { ... };
  export type StreamEventKind = "message_start" | "chunk_delta" | ...;
  ```

- [ ] `src/constants.ts` — 删除 `TranscriptKind`, `ChunkKind`
  - 所有使用处迁移到 `MessageRole` / `StreamEventKind`

## 第五步：前端 — SSE 消费者迁移

`useAgentStream.ts` 是核心改动文件（~545 行），需要从旧 Transcript 模型迁移到新 Message 模型。

### 5.1 状态模型

- [ ] `transcripts: DisplayTranscript[]` → `messages: Message[]`
- [ ] 删除 `DisplayTranscript` 的 `subStreams` / `activeSubStream` / `isFlushed` 包装层
- [ ] `lastIdRef` 改用 `message.id`

### 5.2 SSE 事件分发重写

旧逻辑 `dispatchStreamEvent` (L239-344) 完全重写：

- [ ] `ev.event === "chunk"` → `ev.kind === "chunk_delta"`
  ```
  旧：active = { ...active, text: active.text + ev.text }
  新：msg[ev.field] += ev.delta   // 直接追加到 Message 字段
  ```

- [ ] `ev.event === "flush"` → `ev.kind === "message_finish"`
  ```
  旧：upsertTranscript({ id, kind, message, subStreams, isFlushed })
  新：setMessages(prev => prev.map(m => m.id === id ? { ...m, status: "complete" } : m))
  ```

- [ ] 新增 `ev.kind === "message_start"` 处理
  ```
  新：创建占位 Message 加入列表
  { id, turn_id, role: "assistant", status: "streaming", content: "", reasoning: "", tool_calls: [], ... }
  ```

- [ ] 新增 `ev.kind === "chunk_complete"` 处理
  ```
  用于 tool_calls / tool_result 一次性写入
  ```

- [ ] 新增 `ev.kind === "turn_complete"` 处理
  ```
  用于 token 统计和 running 状态切换
  ```

### 5.3 字段映射速查

| 旧 `dispatchStreamEvent` 变量 | 新 `dispatchStreamEvent` 变量 |
|------|------|
| `ev.event` | `ev.kind` |
| `ev.transcript_id` | `ev.message_id` |
| `ev.kind` (thinking/assistant/tool_result) | `ev.field` (reasoning/content/tool_calls) |
| `ev.text` | `ev.delta` |
| `ev.id` | 不再需要 |
| `ev.sub_streams` | 不再需要 |
| `ev.message` (flush 时) | Message 字段已在 chunk_delta 阶段构建完成 |

### 5.4 API 调用更新

- [ ] `reloadTranscripts` → `reloadMessages`
  ```
  旧：data.transcripts.map(t => ({ id: t.id, kind: t.kind, message: t.message, ... }))
  新：data.messages  // 直接就是 Message[]
  ```

- [ ] `truncateTranscripts` → `truncateMessages`（逻辑不变，只改名）

- [ ] `/status` 端点移除
  ```
  旧：finally 块 fetch(/api/session/{sid}/status) → setRunning(false)
  新：turn_complete 事件包含 running 状态，直接在 SSE 回调中 setRunning(false)
  ```

### 5.5 函数/变量重命名

| 旧 | 新 |
|----|-----|
| `transcripts` | `messages` |
| `setTranscripts` | `setMessages` |
| `reloadTranscripts` | `reloadMessages` |
| `truncateTranscripts` | `truncateMessages` |
| `upsertTranscript` | `upsertMessage` |
| `scrollToTranscript` | `scrollToMessage` |
| `lastIdRef` | 不变 |

## 第六步：前端 — 组件迁移

### 6.1 TranscriptCard → MessageCard

- [ ] 重命名文件 `TranscriptCard.tsx` → `MessageCard.tsx`
- [ ] 删除 `SubStream` import，直接读 `Message` 字段
  ```
  旧：if (t.kind === TranscriptKind.UserQuestion)
  新：if (m.role === "user")
  ```
- [ ] 流式渲染：`m.status === "streaming"` 替代 `!t.isFlushed`
- [ ] 推理块：`m.reasoning` 直接渲染（不再从 `subStreams` 提取）
- [ ] Tool call 卡片：`m.tool_calls` 直接遍历（不再从 `subStreams` 提取）
- [ ] Tool result 卡片：`m.tool_result` 直接渲染

### 6.2 AgentDemo.tsx

- [ ] import `MessageCard` 替代 `TranscriptCard`
- [ ] `transcripts` → `messages`（来自 useAgentStream 返回值）
- [ ] `SessionCache` → 更新 key 名 `transcripts` → `messages`
- [ ] Props 类型更新

### 6.3 pairTools.ts

- [ ] `DisplayTranscript` → `Message`
- [ ] `t.kind` → `m.role`
- [ ] `t.isFlushed` → `m.status === "complete"`
- [ ] `callTranscriptId` → `callMessageId`

### 6.4 ToolPairCard.tsx / CommitGraphPanel.tsx

- [ ] `callTranscriptId` → `callMessageId`
- [ ] `onScrollToTranscript` → `onScrollToMessage`

## 第七步：验证

- [ ] 后端 `/openapi.json` 含完整 Message schema
- [ ] `npm run gen-types` 生成 `types.generated.ts` 无错误
- [ ] `npx tsc --noEmit` 前端编译通过
- [ ] 端到端：发送消息 → SSE 流式返回 → 前端正确渲染 reasoning / content / tool_calls / tool_result
- [ ] 中断测试：中断后前端收到 `interrupted` 事件并正确停止
- [ ] 历史加载：刷新页面后 `recover` 正确回放历史消息
