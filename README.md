# Byte E2E Agent

ReAct 智能体 + FastAPI 后端 + React/Vite 前端。后端以 Message 为核心数据模型，通过 Hook 系统把模型流、工具调用、持久化、指标和 SSE 广播串起来。

## 项目结构

```text
byte_e2e_agent/
├── README.md
├── start.sh                   # 一键启动前后端
├── start-cli.sh               # CLI 终端对话
├── lint.sh                    # 一键 Lint
├── .gitignore
├── docs/                      # 架构文档与变更记录
├── backend/
│   ├── pyproject.toml         # Python 依赖（uv 管理）
│   ├── uv.lock                # Python 锁定文件
│   ├── .python-version        # Python 3.14
│   ├── .env.example           # 环境变量模板
│   ├── main.py                # FastAPI + uvicorn 入口
│   ├── cli.py                 # 命令行对话入口
│   ├── shared/                # 前后端共享类型 + Hook 基础设施
│   ├── app/
│   │   ├── api/               # FastAPI routes / SSE helper
│   │   ├── core/              # 配置 / CORS
│   │   ├── schemas/           # 请求和响应模型
│   │   └── services/          # 业务层：chat / session / checkpoint / metrics
│   ├── agent/
│   │   ├── actions.py         # model_call / execute_one_tool / subagent invoke
│   │   ├── llm.py             # OpenAI 客户端工厂
│   │   ├── tool_execution.py  # 工具批量执行 + guard
│   │   ├── shadow_repo.py     # Dulwich shadow git repo
│   │   ├── metrics.py         # SQLite LLM 指标
│   │   ├── core/              # Workspace / SessionConfig / prompts
│   │   ├── hook/              # StreamDriver / Metrics / Persistence / ShadowCommit
│   │   ├── memory/            # 长期记忆（MemoryStore + MemoryHook）
│   │   ├── runtime/           # AgentRuntime / context_builder / driver / subagents
│   │   ├── session/           # Session 数据容器 + JSONL 持久化
│   │   └── tools/             # Shell / file I/O / grep / browser / task / skill
│   └── tests/
└── frontend/
    ├── package.json
    ├── eslint.config.js
    ├── tsconfig.json
    ├── vite.config.ts
    └── src/
        ├── components/        # AgentDemo / MessageCard / SessionSidebar / CommitGraphPanel
        ├── hooks/             # useAgentStream / messageReducer / pairTools
        ├── types.ts           # 前端手写协议类型
        └── types.generated.ts # OpenAPI 自动生成
```

## 环境要求

| 工具 | 版本 | 检查 |
|------|------|------|
| Python | 3.14+ | `python --version` |
| uv | 最新版 | `uv --version` |
| Node.js | 20+ | `node --version` |
| npm | 10+ | `npm --version` |
| Chromium | Playwright | `cd backend && uv run playwright install chromium` |

## 快速开始

### 1. 配置环境变量

```bash
cp backend/.env.example backend/.env
```

至少需要：

```text
LLM_API_KEY=...
LLM_BASE_URL=...
LLM_MODEL_ID=...
```

### 2. 一键启动

```bash
./start.sh
```

前端 `http://localhost:5173`，API 文档 `http://localhost:8000/docs`。

### 3. 分别启动

后端：

```bash
cd backend
uv sync
uv run uvicorn main:app --reload --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev
```

### 4. CLI 终端

```bash
./start-cli.sh                    # REPL 交互
./start-cli.sh "帮我写排序函数"    # 单次提问
```

---

## 开发命令

### 一键 Lint

```bash
./lint.sh                    # 前后端全量
./lint.sh --backend          # 仅后端
./lint.sh --frontend         # 仅前端
./lint.sh --fix              # 全量 + auto-fix
./lint.sh --backend --fix    # 后端 + auto-fix
```

### 分别运行

| 位置 | 命令 | 说明 |
|------|------|------|
| 后端 | `uv run ruff check .` | Lint |
| 后端 | `uv run ruff check . --fix` | Lint + 自动修复 |
| 后端 | `uv run ruff format .` | 格式化 |
| 后端 | `uv run pytest tests/ -q` | 测试 |
| 前端 | `npm run lint` | ESLint |
| 前端 | `npm run lint -- --fix` | ESLint + 自动修复 |
| 前端 | `npm run test` | Vitest |
| 前端 | `npm run build` | 生产构建 |

---

## 核心架构

```text
React frontend
  ↕ REST + SSE (StreamEvent)
FastAPI routes
  ↕
WorkspaceContext
  ├─ AgentRuntime          — ReAct 主循环
  ├─ HookManager
  │   ├─ StreamDriverHook      → SSE 广播
  │   ├─ PersistenceHook       → messages.jsonl
  │   ├─ MetricsHook           → SQLite metrics
  │   ├─ ShadowCommitHook      → shadow git 快照
  │   └─ MemoryHook            → 长期记忆
  └─ ShadowRepo (Dulwich)
```

### 分层职责

- `app/api/` — HTTP 参数、响应模型、SSE 传输、状态码映射
- `app/services/` — 业务动作：chat、session recovery、checkpoint restore
- `agent/runtime/` — ReAct 主循环、工具执行、subagent invoke、interrupt/pending
- `agent/hook/` — 纯旁路通知（SSE、持久化、指标、快照、记忆），异常不影响主循环
- `agent/session/` — Message 数据容器 + JSONL 磁盘持久化

## Message 和 SSE

`shared/types.py` 中的 `Message` 是持久化、SSE 协议和前端渲染的共同数据模型。所有上下文（system prompt、skills、tasks、memory）均为 append-only 的系统消息，存储在 Session JSONL 中，确保 KV-cache 前缀稳定性。

SSE 事件流：

```text
message_start → chunk_delta → chunk_complete → message_finish → turn_complete
                                                              → interrupted
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | — | API 密钥 |
| `LLM_BASE_URL` | — | API 端点 |
| `LLM_MODEL_ID` | — | 模型 ID |
| `LLM_TIMEOUT` | `60` | 请求超时（秒） |
| `AGENT_WORKSPACE` | 当前目录 | 默认 workspace |
| `LLM_MAX_RETRIES` | `3` | 模型请求最大重试次数 |
| `MEMORY_ENABLED` | `0` | 是否启用长期记忆 |
| `SIDE_LLM_API_KEY` | `LLM_API_KEY` | 记忆 side-query API key |
| `SIDE_LLM_BASE_URL` | `LLM_BASE_URL` | 记忆 side-query endpoint |
| `SIDE_LLM_MODEL_ID` | `LLM_MODEL_ID` | 记忆 side-query model |
| `BROWSER_HEADLESS` | `1` | `0` = 有头模式 |
| `SERPAPI_KEY` | — | WebSearch 工具 |

## 数据路径

```text
{workspace}/.byte_agent/
  sessions/{session_id}/
    session.json
    config.json
    messages.jsonl       # append-only 消息历史
    tasks.json           # 任务看板
  .shadow-vcs/           # shadow git 仓库
  ai_metrics.sqlite3     # LLM 指标
  memory.db              # 长期记忆（需 MEMORY_ENABLED=1）
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/workspace` | 当前 workspace |
| `POST` | `/api/workspace/set` | 切换 workspace |
| `POST` | `/api/session` | 创建 session |
| `GET` | `/api/sessions` | 当前 workspace 的 session 列表 |
| `DELETE` | `/api/session/{sid}` | 删除 session |
| `GET` | `/api/session/{sid}/history` | 获取历史消息 |
| `POST` | `/api/session/{sid}/chat` | 启动 Agent（SSE） |
| `GET` | `/api/session/{sid}/stream` | SSE 断线重连 |
| `GET` | `/api/session/{sid}/recover` | 恢复消息和运行状态 |
| `POST` | `/api/session/{sid}/respond` | 响应 pending 请求 |
| `POST` | `/api/session/{sid}/interrupt` | 中断 session |
| `GET` | `/api/session/{sid}/commits` | shadow commit 列表 |
| `POST` | `/api/session/{sid}/workspace/restore` | 恢复到指定 commit |
| `POST` | `/api/session/{sid}/messages/truncate` | 截断消息历史 |
| `GET` | `/api/metrics/llm/calls` | LLM 调用明细 |
| `GET` | `/api/metrics/llm/summary` | LLM 调用汇总 |
| `GET` | `/api/metrics/llm/dashboard` | LLM 仪表盘 |
| `GET` | `/api/status` | 运行时状态 |
