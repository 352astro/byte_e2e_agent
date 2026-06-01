# Byte E2E Agent

ReAct 智能体 + FastAPI 后端 + React/Vite 前端。后端以 Message 为核心数据模型，通过 Hook 系统把模型流、工具调用、持久化、指标和 SSE 广播串起来。

## 项目结构

```text
byte_e2e_agent/
├── start.sh                   # 一键启动前后端
├── docs/                      # 架构文档与变更记录
├── backend/
│   ├── main.py                # FastAPI app + uvicorn 入口
│   ├── .python-version        # Python 3.14
│   ├── .env.example           # 环境变量模板
│   ├── pyproject.toml         # Python 依赖，uv 管理
│   ├── uv.lock                # Python 锁定文件
│   ├── shared/                # 前后端共享类型 + Hook 基础设施
│   ├── app/
│   │   ├── api/               # FastAPI routes / SSE helper
│   │   ├── core/              # 配置 / CORS
│   │   ├── schemas/           # 请求和响应模型
│   │   ├── services/          # 业务层：chat/session/checkpoint/workspace/metrics
│   │   │   ├── context.py     # WorkspaceContext：runtime、hooks、shadow repo、metrics
│   │   │   └── session_scope.py # session_id -> workspace 解析
│   │   └── dependencies.py    # 依赖注入
│   └── agent/
│       ├── runtime.py         # AgentRuntime：Session 管理 + ReAct 主循环
│       ├── actions.py         # model_call / execute_one_tool / subagent invoke
│       ├── core/              # Workspace / SessionConfig / prompts
│       ├── hook/              # StreamDriver / Metrics / Persistence / ShadowCommit
│       ├── session/           # Session 数据容器 + JSONL 持久化
│       ├── tools/             # Shell / file I/O / grep / browser / task / skill
│       ├── shadow_repo.py     # Dulwich shadow git repo
│       └── metrics.py         # SQLite LLM 指标
├── frontend/
│   ├── src/
│   │   ├── components/        # AgentDemo / MessageCard / SessionSidebar
│   │   ├── hooks/             # useAgentStream / reducer / pairing
│   │   ├── types.ts           # 前端手写协议类型
│   │   └── types.generated.ts # OpenAPI 生成类型
│   ├── package.json
│   └── package-lock.json
└── README.md
```

## 环境要求

| 工具 | 版本 | 检查 |
|------|------|------|
| Python | 3.14+ | `python --version` |
| uv | 最新稳定版 | `uv --version` |
| Node.js | 20+ | `node --version` |
| npm | 10+ | `npm --version` |
| Chromium | Playwright 安装 | `uv run playwright install chromium` |

## 快速开始

### 1. 配置环境变量

```bash
cp backend/.env.example backend/.env
```

至少需要配置：

```text
LLM_API_KEY=...
LLM_BASE_URL=...
LLM_MODEL_ID=...
```

### 2. 一键启动

```bash
./start.sh
```

前端默认在 `http://localhost:5173`，后端 API 文档在 `http://localhost:8000/docs`。

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

### 4. Playwright 浏览器工具

```bash
cd backend
uv run playwright install chromium
```

有头模式需要可用图形环境，并在 `.env` 中设置：

```text
BROWSER_HEADLESS=0
```

## 依赖管理

后端使用 `uv`：

```bash
cd backend
uv lock --upgrade
uv sync
```

前端使用 npm：

```bash
cd frontend
npm update --save
npm install
```

注意：`openapi-typescript@7.x` 的 peer dependency 要求 TypeScript 5.x，因此前端当前保持 `typescript@^5.9.3`，不是 6.x。

## 数据和路径

项目有两个内部存储层：

```text
PROJECT_ROOT/.agent/workspaces.json
```

保存已注册 workspace 列表。

```text
{workspace}/.byte_agent/
  sessions/{session_id}/
    session.json
    config.json
    messages.jsonl
    tasks.json
  .shadow-vcs/
  ai_metrics.sqlite3
```

保存每个 workspace 自己的 session、消息、shadow repo 和默认指标库。

`session.json` 持久化 session 所属 workspace。后端收到 `/api/session/{sid}/...` 请求时会先通过 `SessionLocator` 解析真实 workspace，再使用对应的 scoped `WorkspaceContext` 执行工具、路径检查、消息读取和快照操作。

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | Hello World |
| `GET` | `/api/hello` | Hello World |
| `GET` | `/api/workspace` | 当前 workspace |
| `POST` | `/api/workspace/set` | 切换当前 workspace |
| `POST` | `/api/session` | 在当前 workspace 创建 session |
| `GET` | `/api/sessions` | 当前 workspace 的 session |
| `GET` | `/api/sessions/all` | 已注册 workspace 下的全部 session |
| `DELETE` | `/api/session/{sid}` | 删除 session |
| `GET` | `/api/session/{sid}/history` | 获取历史消息 |
| `POST` | `/api/session/{sid}/chat` | 启动 Agent，返回 SSE |
| `GET` | `/api/session/{sid}/stream` | SSE 断线重连 |
| `GET` | `/api/session/{sid}/recover` | 恢复消息和运行状态 |
| `GET` | `/api/status` | runtime busy 状态 |
| `GET` | `/api/session/{sid}/status` | session running + runtime busy 状态 |
| `POST` | `/api/session/{sid}/respond` | 响应 pending 请求 |
| `GET` | `/api/session/{sid}/commits` | shadow commit 列表 |
| `GET` | `/api/session/{sid}/commits/{sha}` | shadow commit 详情 |
| `POST` | `/api/session/{sid}/workspace/restore` | 恢复 workspace 到指定 commit |
| `POST` | `/api/session/{sid}/messages/truncate` | 截断消息历史 |
| `POST` | `/api/session/{sid}/interrupt` | 中断指定 session |
| `POST` | `/api/interrupt` | 中断当前运行任务 |
| `GET` | `/api/metrics/llm/calls` | LLM 调用明细 |
| `GET` | `/api/metrics/llm/summary` | LLM 调用汇总 |
| `GET` | `/api/metrics/llm/dashboard` | LLM 仪表盘 |

状态字段语义：

- `running`：在 session 相关接口中表示该 session 是否正在运行；在 `/api/status` 中为兼容字段，等同 `runtime_busy`。
- `runtime_busy`：任意 scoped runtime 是否正在运行。

## 核心架构

```text
React frontend
  ↕ REST + SSE(StreamEvent)
FastAPI routes
  ↕
Services
  ├─ SessionLocator / SessionScope
  └─ WorkspaceContext
       ├─ AgentRuntime
       ├─ HookManager
       │   ├─ StreamDriverHook      -> SSE
       │   ├─ PersistenceHook       -> messages.jsonl
       │   ├─ MetricsHook           -> SQLite metrics
       │   └─ ShadowCommitHook      -> shadow commits
       ├─ ShadowRepo
       └─ CoreWorkspace
            ├─ resolve()            -> path traversal guard
            ├─ run_shell()
            └─ file I/O
```

### 分层职责

- `routes/` 只处理 HTTP 参数、响应模型、SSE response 和 HTTP status 映射。
- `services/` 处理业务动作，例如 chat、session recovery、checkpoint restore。
- `WorkspaceContext` 持有 workspace 级运行时状态：runtime、hooks、shadow repo、metrics store。
- `AgentRuntime` 拥有 ReAct 主循环、tool execution、subagent invoke、interrupt/pending 状态。

## Long-term Memory

长期记忆默认关闭，通过 `MEMORY_ENABLED=1` 开启。实现位于 `backend/agent/memory/`：

- `SQLiteMemoryStore` 存储在 `{workspace}/.byte_agent/memory.db`
- SQLite 负责持久化、scope/kind 粗筛和去重，不依赖 embedding 或向量数据库
- `MemoryHook` 在 turn 结束时用 side-query LLM 提取结构化记忆和简短 `feature`
- 记忆字段包括 `scope`、`kind`、`confidence`、`content`、`feature`、`content_hash`
- 当前支持 `workspace` 和 `session` scope；删除 session 时只清理 session-scope memory
- 召回时按 workspace/session 过滤候选，把短 `feature` 列表交给 side-query LLM 选择，再注入为 `## Long-term Memory` system context

记忆提取会过滤常见 secret/token/password 内容。side-query LLM 可用 `SIDE_LLM_*` 单独配置；未配置时回退到 `LLM_*`。

## Message 和 SSE

`shared/types.py` 中的 `Message` 是后端持久化、SSE 协议和前端渲染的共同数据模型。

SSE 事件顺序：

```text
message_start
chunk_delta
chunk_complete
message_finish
turn_complete
interrupted
```

前端 `useAgentStream` 对 `chunk_delta` 直接执行字段追加，对 `chunk_complete` 做结构化字段收束。

## 工具和 SubAgent

工具由 async handler + LangChain `StructuredTool.from_function()` 包装，并注册进 `ToolRegistry`。运行时会把 `ws`、`session_id`、`interrupt_event` 注入支持这些参数的工具。

SubAgent 当前是 invoke 式独立 session：父 agent 调用后进入等待，子 session 完成后把结果作为 tool result 返回父 agent。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | — | API 密钥 |
| `LLM_BASE_URL` | — | API 端点 |
| `LLM_MODEL_ID` | — | 模型 ID |
| `LLM_TIMEOUT` | `60` | 请求超时，秒 |
| `AGENT_WORKSPACE` | repo 根目录 | 默认 workspace |
| `LLM_METRICS_DB_PATH` | `.byte_agent/ai_metrics.sqlite3` | 指标数据库；相对路径按 workspace 解析 |
| `MEMORY_ENABLED` | `0` | 是否启用长期记忆 |
| `MEMORY_TOP_K` | `5` | 注入上下文的记忆数量 |
| `MEMORY_RECALL_TOP_K` | `30` | 交给 side-query LLM 挑选的候选记忆上限 |
| `MEMORY_LLM_TIMEOUT` | `10` | side-query LLM 超时，秒 |
| `SIDE_LLM_API_KEY` | `LLM_API_KEY` | 长期记忆 side-query API key |
| `SIDE_LLM_BASE_URL` | `LLM_BASE_URL` | 长期记忆 side-query endpoint |
| `SIDE_LLM_MODEL_ID` | `LLM_MODEL_ID` | 长期记忆 side-query model |
| `BROWSER_HEADLESS` | `1` | `0` 为有头模式 |
| `SERPAPI_KEY` | — | WebSearch |
| `LLM_INPUT_COST_YUAN_PER_1M_TOKENS` | `3` | 输入 token 成本 |
| `LLM_OUTPUT_COST_YUAN_PER_1M_TOKENS` | `6` | 输出 token 成本 |

## 常用检查

```bash
cd backend
python -m py_compile app/services/context.py app/services/session_scope.py app/services/session_service.py
```

```bash
cd frontend
npm run build
```

## Skill 扩展

```bash
mkdir -p backend/agent/skills/my_skill
$EDITOR backend/agent/skills/my_skill/SKILL.md
```

也可以通过 `SubAgent(with_skills=["my_skill"])` 在启动子智能体时注入 skill。
