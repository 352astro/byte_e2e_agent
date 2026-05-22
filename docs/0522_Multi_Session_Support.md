# 2026-05-22 — 多会话支持

## 变更

### Turn 模型 & 历史接口

引入 `agent/turn.py` — `Turn` + `ToolStep` 作为 `_turns` 与前端共用的规范化快照。

| 文件 | 变更 |
|------|------|
| `backend/agent/turn.py` | **新增** — `Turn` / `ToolStep` dataclass |
| `backend/agent/react.py` | `run_stream()` 同步产出 `Turn` 列表；`get_history()` 方法 |
| `backend/session_manager.py` | `get_history(sid)` 代理 |
| `backend/main.py` | `GET /api/session/{sid}/history` 端点 |
| `frontend/src/hooks/useAgentStream.js` | 会话切换时若缓存未命中，fetch history 并转换为 steps/messages |

**数据流**：`run_stream()` → SSE 事件（前端实时渲染）+ Turn 快照（存储）→ `GET /history` → 前端刷新后重建 UI。


### 新增

| 文件 | 说明 |
|------|------|
| `backend/session_manager.py` | `SessionManager` — UUID → Agent 实例映射，共享 LLM 客户端 |
| `frontend/src/components/SessionSidebar.jsx` | 左侧会话列表侧边栏 |

### 修改

| 文件 | 变更 |
|------|------|
| `backend/main.py` | 新增 `POST /api/session`、`GET /api/sessions`、`POST /api/session/{sid}/chat` |
| `frontend/src/App.jsx` | sidebar + main 布局；session 选择/新建逻辑 |
| `frontend/src/components/AgentDemo.jsx` | 接受 `sessionId`/`pendingNew` props |
| `frontend/src/hooks/useAgentStream.js` | 懒创建会话：首次发送时 `POST /api/session` 再聊天 |
| `frontend/src/App.css` | sidebar + layout 样式 |

### 不变

- `backend/agent/` 目录 — 零改动

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/session` | 新建会话，返回 `{"session_id":"abc123"}` |
| `GET` | `/api/sessions` | 列出所有会话 ID |
| `POST` | `/api/session/{sid}/chat` | 对指定会话发起 SSE 流式对话 |
| `POST` | `/api/agent/stream` | 遗留（无状态，每次新建临时会话） |


### 修复 & 增强

**会话切换渲染修复**：移除 `key={sessionId}`（避免 AgentDemo 重挂载丢失状态）。
改为 `sessionCache` 对象在切换时保存/恢复 `{steps, answer, messages}`。

**用户消息气泡**：每次发送后，用户消息以紫色高亮气泡 `💬 You` 显示在步骤卡片上方，
支持同一 Session 内持续对话。

| 文件 | 变更 |
|------|------|
| `src/App.jsx` | `sessionCache` 持久化；移除 `key` prop |
| `src/hooks/useAgentStream.js` | `useEffect` 保存/恢复会话状态；`messages` 状态管理 |
| `src/components/AgentDemo.jsx` | 接受 `cache` prop；渲染用户气泡 |
| `src/components/AgentDemo.css` | 新增 `.user-bubble` 样式 |

## 前端流程

```
1. 点击 "+ New Session" → 进入空白 agent 页面
2. 用户输入消息 → 首次发送时 POST /api/session 创建会话
3. 拿到 session_id → POST /api/session/{id}/chat 开始对话
4. 结果流式返回，渲染在页面上
5. 用户可在侧边栏切换回之前的会话继续对话
```
