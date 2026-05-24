# 2026-05-23 — Scheduler + Transcript + StreamChannel 架构设计

## 动机

当前 `run_stream` 直接通过 SSE 向前端推送事件。存在三个根本缺陷：

1. **SSE 连接即执行上下文**：连接断开（刷新/网络波动）→ async generator 死亡，所有流式中
   间状态（推理 token、工具输出、等待用户交互）全部丢失
2. **`_messages` 信息密度低**：仅 OpenAI 消息格式，无法承载 permission_request /
   user_input / clarify 等交互型事件，且无唯一标识字段供前后端精确引用
3. **恢复依赖前端缓存**：`get_history()` 只能恢复已完成的消息边界，不能恢复一个
   输出了 300 token 但未完成的 assistant 回复，也不能恢复一个等待批准的权限请求

## 核心概念

### Transcript — 一等存储单元

```
Transcript {
    id: str            # 唯一标识 (UUID)，贯穿该事件的整个生命周期
    kind: str          # 事件类型
    message: dict      # 结构化负载
}
```

`kind` 枚举：

| kind | 说明 | message 关键字段 |
|------|------|-----------------|
| `user_question` | 用户提问 | `content` |
| `reasoning` | 推理过程（一段连续 token 的完整结果） | `content` |
| `assistant_text` | LLM 文本回复（无 tool_calls 时） | `content` |
| `tool_call` | 工具调用 | `tool_name`, `arguments`, `tool_call_id` |
| `tool_result` | 工具执行结果 | `tool_call_id`, `result` |
| `tool_stream_chunk` | 工具执行的实时输出（如 Shell 终端） | `tool_call_id`, `chunk` |
| `tool_stream_flush` | 工具流式输出完成 | `tool_call_id`, `full_output` |
| `permission_request` | 请求用户授权 | `tool_call_id`, `tool_name`, `command` |
| `permission_response` | 用户授权结果 | `tool_call_id`, `approved` |
| `final_answer` | 最终回答 | `content` |
| `error` | 错误 | `message` |

### StreamChannel — 流式通道

```
StreamChannel(session_id)
  ├── _transcripts: dict[id, Transcript]     # 全量（持久化 + 恢复用）
  ├── _active_triggers: set[id]              # 当前正在流式输出的 transcript_id
  ├── _subscribers: list[asyncio.Queue]      # 当前激活的 SSE 订阅者
  │
  ├── chunk(id, text)          # 发送增量 → SSE + 内部累积到 _transcripts[id]
  ├── flush(id, payload)       # 发送完整 → 覆盖累积，从 _active_triggers 移除
  ├── subscribe() → Queue      # 新 SSE 连接订阅
  ├── unsubscribe(queue)       # SSE 连接断开
  └── get_since(last_id) → list[Transcript]  # 断线追补
```

**`chunk` vs `flush`**：

同一个 `transcript_id` 先发若干 `chunk`（前端增量渲染），最后发一次 `flush`（前端替换为完整版，后端从 `_active_triggers` 移除该 id）。刷新追补时，已完成（已 flush）的 transcript 返回完整内容，仍在进行中（未 flush）的 transcript 返回当前累积内容。

### Scheduler — 调度器

```
Scheduler(session_id)
  ├── _loop_task: asyncio.Task | None
  ├── _state: "idle" | "running" | "awaiting_input"
  ├── _pending: dict[transcript_id, {event: asyncio.Event, response: dict | None}]
  └── _channel: StreamChannel

  ├── start(question) → stream_uuid
  │    创建 _loop_task = asyncio.create_task(query_loop(question))
  │    返回 stream_uuid（即 channel 的唯一标识，与 session_id 1:1）
  │
  ├── resolve(transcript_id, response)
  │    唤醒 _pending[transcript_id].event
  │
  └── query_loop(question)
        ┌─ emit user_question transcript
        ├─ while not done:
        │    ├─ model_call() → emit reasoning + assistant_text / tool_call
        │    ├─ permission_check → emit permission_request + await (可暂停)
        │    ├─ tool_execute → emit tool_stream_chunk/flush + tool_result
        │    └─ persist → 写入 SessionMemory
        └─ emit final_answer
```

### 状态机

```
 idle ──start()──→ running ──finish──→ idle
                     │                    ↑
                     │ permission_needed  │ timeout
                     ▼                    │
               awaiting_input ──resolve──┘
```

---

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/session/{sid}/chat` | 创建 query_loop 任务，返回 `{ stream_uuid }` |
| `GET` | `/api/session/{sid}/recover` | 一次性返回完整恢复信息 |
| `GET` | `/api/stream/{stream_uuid}?since=last_transcript_id` | SSE，订阅流式通道 |
| `POST` | `/api/respond/{stream_uuid}` | 用户交互响应 |

### `GET /api/session/{sid}/recover` 返回值

```json
{
  "transcripts": [
    {"id": "t1", "kind": "user_question", "message": {...}},
    {"id": "t2", "kind": "tool_call", "message": {...}},
    {"id": "t3", "kind": "tool_result", "message": {...}}
  ],
  "stream_uuid": "abc-123",
  "pending": {
    "transcript_id": "t4",
    "kind": "permission_request",
    "message": {"tool_call_id": "call_1", "tool_name": "Shell", "command": "rm -rf /"}
  }
}
```

| 字段 | 场景 | 前端行为 |
|------|------|---------|
| `transcripts` | 始终存在 | 渲染已完成的历史 |
| `stream_uuid: null` | 无活跃流 | 不建立 SSE 连接 |
| `stream_uuid: "..."` | 后台 query_loop 执行中 | 打开 `GET /stream/{uuid}` 追补 + 订阅 |
| `pending: {...}` | 等待用户交互 | 渲染对应 UI（权限弹窗 / 输入框 / 选择器） |

### `GET /api/stream/{stream_uuid}` — SSE 事件

```
event: chunk
data: {"transcript_id": "t1", "text": "hel"}

event: chunk
data: {"transcript_id": "t1", "text": "lo"}

event: flush
data: {"transcript_id": "t1", "full": "hello world", "kind": "assistant_text"}

event: request
data: {"transcript_id": "t2", "kind": "permission_request", "message": {...}}
```

### `POST /api/respond/{stream_uuid}`

```json
// Request
{ "transcript_id": "t2", "response": { "approved": true } }

// Response
{ "ok": true }
```

---

## 交互流程（以 Permission 为例）

```
1. Scheduler query_loop 中 tool_call 前检查:
   if needs_permission:
       perm_id = uuid4()
       self._channel.flush(perm_id, {"kind": "permission_request", ...})
       event = asyncio.Event()
       self._pending[perm_id] = {"event": event, "response": None}
       self._state = "awaiting_input"
       await event.wait()    # ← 挂起（event loop 处理其他任务）
       self._state = "running"
       response = self._pending.pop(perm_id)["response"]
       if not response.get("approved"):
           return  # 跳过工具

2. 前端收到 flush(perm_id, permission_request):
   → 渲染权限弹窗

3. 用户点击"批准":
   → POST /respond/{stream_uuid} { transcript_id: perm_id, response: {approved: true} }

4. resolve(perm_id, {approved: true}):
   → self._pending[perm_id]["response"] = {approved: true}
   → self._pending[perm_id]["event"].set()
   → query_loop 从 await 处恢复，拿到 response
```

### 刷新恢复场景

```
场景: 权限弹窗展示中，用户刷新页面

刷新前:
  Scheduler._state = "awaiting_input"
  Scheduler._pending["t42"] = {event: Event(), response: None}
  StreamChannel._transcripts["t42"] = Transcript(kind="permission_request", ...)

刷新后:
  GET /recover → {
    transcripts: [...已完成的...],
    stream_uuid: "abc",
    pending: { transcript_id: "t42", kind: "permission_request", message: {...} }
  }
  → 前端重建历史 + 重新渲染权限弹窗（transcript_id: "t42"）
  → 打开 GET /stream/abc 订阅
  → 用户点击 → POST /respond/abc { transcript_id: "t42", response: {...} }
  → Scheduler 仍在后台运行，event.set() 唤醒
```

---

## 前端适配

### 1. 新增 `stream_uuid` 状态

```
useAgentStream:
  streamUuid: string | null  ← 从 /recover 或 /chat 获取
  若 streamUuid 非 null → 立即订阅 GET /stream/{streamUuid}
```

### 2. chunk/flush 去重逻辑

```
收到 chunk(id="t1", text="hel")     → 在 pendingMap[id] 累积
收到 chunk(id="t1", text="lo")      → 同上
收到 flush(id="t1", full="hello!")  → 从 pendingMap 移除 id，渲染 flush 内容

刷新追补:
  GET /recover → transcripts 列表
  → pendingMap: 遍历 transcripts，已 flush 的跳过（不在 _active_triggers 中）
  → 对未 flush 的 transcript，从 chunk 累积重建当前状态
```

### 3. 交互 UI 渲染

```
ToolRenderers:
  transcript.kind === "permission_request" → <PermissionDialog transcriptId={id} ... />
  transcript.kind === "input_request"      → <InputForm transcriptId={id} ... />
  transcript.kind === "select_request"     → <SelectDialog transcriptId={id} ... />

用户操作 → POST /respond/{streamUuid} { transcript_id, response }
```

---

## 改动清单

### 后端

| 文件 | 改动 | 说明 |
|------|------|------|
| `agent/transcript.py` | **新增** | `Transcript` 数据类定义 |
| `agent/stream_channel.py` | **新增** | `StreamChannel`：chunk/flush/subscribe/get_since |
| `agent/scheduler.py` | **新增** | `Scheduler`：query_loop、resolve、状态机 |
| `agent/react.py` | **重构** | 移除 `run_stream` 及 `_execute_one_tool`，替换为 Scheduler 调用 |
| `main.py` | **修改** | 新增 `GET /recover`、`GET /stream/{uuid}`、`POST /respond/{uuid}`；改造 `POST /chat` |
| `agent/session_memory.py` | **适配** | `append_message` → `append_transcript`；`load` 返回 transcripts |

### 前端

| 文件 | 改动 | 说明 |
|------|------|------|
| `src/types.ts` | **新增** | `Transcript`、`RecoverResponse`、`StreamEvent` 类型 |
| `src/hooks/useAgentStream.ts` | **重构** | 新增 stream_uuid 订阅；chunk/flush 去重；pending 渲染 |
| `src/components/ToolRenderers.tsx` | **新增** | `PermissionDialog`、`InputForm`、`SelectDialog` 组件 |

### 删除

| 文件 | 原因 |
|------|------|
| `agent/react.py` 中 `run_stream`、`_execute_one_tool`、`_stream_llm`、`_LLMOutput` | 逻辑迁移到 Scheduler |

---

## 不变部分

- `agent/tools/` — 全部工具定义不动
- `agent/plan_manager.py` — 计划管理不动
- `agent/sandbox.py` — 沙箱不动（仅新增 `needs_permission` 判定方法）
- `agent/llm.py` — LLM 客户端不动
- `agent/terminal.py` — 终端不动
- 前端 CSS — 不动
- 前端 Markdown / SessionSidebar — 不动

---

## 与旧设计（0523_Interactive_User_Input_Design.md）的关键区别

| | 旧设计 | 新设计 |
|---|---|---|
| 执行上下文 | SSE 连接即 async generator | 后台 asyncio.Task，SSE 仅作订阅 |
| 刷新恢复 | 不可能 | 完整恢复：历史 + 流式进度 + 交互请求 |
| 存储单元 | `_messages: list[dict]` | `Transcript(id, kind, message)` |
| 暂停机制 | `asyncio.Future` | `asyncio.Event`（可复用信号量） |
| 前后端索引 | `request_id`（临时 UUID） | `transcript_id`（全局唯一，存入 channel） |
| 前端去重 | 无 | chunk/flush + transcript_id 关联 |
