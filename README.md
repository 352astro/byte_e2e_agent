# Byte E2E Agent

ReAct 智能体 + FastAPI 后端 + React (Vite) 前端。

## 项目结构

```
byte_e2e_agent/
├── start.sh                   # 一键启动前后端
├── docs/                      # 架构文档与变更记录
├── backend/
│   ├── main.py                # FastAPI app factory + uvicorn 入口
│   ├── .python-version        # Python 3.14
│   ├── .env.example           # 环境变量模板
│   ├── pyproject.toml         # 依赖（uv 管理）
│   ├── requirements.txt       # 依赖（pip 兼容）
│   ├── uv.lock                # 锁定文件
│   ├── shared/                # 前后端共享类型 + Hook 基础设施
│   │   ├── types.py           # Message / StreamEvent / ToolCall / Turn
│   │   └── hooks.py           # BaseHook / HookManager
│   ├── app/                   # FastAPI 应用层
│   │   ├── api/
│   │   │   ├── router.py      # 路由聚合
│   │   │   ├── sse.py         # SSE 辅助
│   │   │   └── routes/        # sessions / chat / metrics
│   │   ├── core/              # 配置 / CORS
│   │   ├── schemas/           # 请求模型
│   │   ├── services/
│   │   │   └── project.py     # Project 编排（Workspace + Session + Runtime）
│   │   └── dependencies.py    # 依赖注入
│   └── agent/
│       ├── actions.py         # model_call / execute_one_tool / run_subagent
│       ├── runtime.py         # AgentRuntime：多 Session 管理 + ReAct 主循环
│       ├── llm_lc.py          # LangChain ChatOpenAI 工厂
│       ├── shadow_repo.py     # Git 工作区快照（Dulwich）
│       ├── metrics.py         # SQLite LLM 调用追踪
│       ├── tools/             # 工具系统（LangChain StructuredTool）
│       │   ├── registry.py    # ToolRegistry 注册表 + OpenAI schema 生成
│       │   ├── toolset.py     # ToolSet 按名称构建子集
│       │   ├── shell.py       # Shell 命令执行
│       │   ├── read.py        # 文件读取
│       │   ├── write.py       # 文件写入
│       │   ├── edit.py        # 查找替换编辑
│       │   ├── grep.py        # 正则搜索
│       │   ├── glob.py        # 文件匹配
│       │   ├── search.py      # WebSearch / WebFetch
│       │   ├── subagent.py    # 子智能体
│       │   ├── browser.py     # 浏览器交互（Playwright）
│       │   ├── task.py        # 任务管理
│       │   ├── skill.py       # Skill 加载
│       │   └── pyrepl.py      # 安全 Python REPL
│       ├── core/
│       │   ├── workspace.py   # Workspace：路径管理 + 纯 I/O
│       │   ├── config.py      # SessionConfig / AgentConfig / AccessPolicy
│       │   ├── hooks.py       # re-export（from shared.hooks）
│       │   ├── types.py       # re-export（from shared.types）
│       │   └── prompts.py     # 系统提示词
│       ├── hook/              # Hook 实现
│       │   ├── stream_driver.py  # SSE 广播
│       │   ├── metrics_hook.py   # SQLite 指标写入
│       │   └── logging_hook.py   # 控制台输出
│       ├── session/           # Session 数据容器 + JSONL 持久化
│       ├── skills/            # Skill Markdown 模块
│       ├── errors/            # InterruptedError / 消息修复管线
│       └── persistence/       # SQLite schema
├── frontend/
│   ├── src/
│   │   ├── main.tsx           # React 入口
│   │   ├── App.tsx            # 应用根组件
│   │   ├── components/        # AgentDemo / Markdown / SessionSidebar
│   │   ├── hooks/             # useAgentStream（SSE 消费）
│   │   └── types.ts           # 前端 Message 类型（镜像 shared/types.py）
│   ├── package.json
│   └── vite.config.ts         # 含 /api 开发代理
└── .gitignore
```

## 环境要求

| 工具 | 最低版本 | 检查 |
|------|----------|------|
| Python | 3.14 | `python --version` |
| Node.js | 20 | `node --version` |
| npm | 10 | `npm --version` |
| Chromium | — | Playwright 自动下载 |

## 快速开始

### 1. 配置环境变量

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env，必填：
#   LLM_API_KEY     — API 密钥
#   LLM_BASE_URL    — API 端点
#   LLM_MODEL_ID    — 模型 ID
```

### 2. 一键启动（推荐）

```bash
./start.sh
```

前后端同时启动。`http://localhost:5173` 打开前端，`http://localhost:8000/docs` 查看 API 文档。

### 3. 分别启动

**后端**

```bash
cd backend
uv sync
uv run uvicorn main:app --reload --port 8000
```

**前端**

```bash
cd frontend
npm install
npm run dev
```

### 4. Playwright 浏览器（可选）

BrowserOpen / BrowserAct / BrowserInspect 依赖 Playwright：

```bash
cd backend
uv run playwright install chromium
```

有头模式（需要 X Server）：在 `.env` 中设置 `BROWSER_HEADLESS=0`。

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | Hello World |
| `GET` | `/api/hello` | Hello World |
| `GET` | `/api/workspace` | 当前工作区 |
| `POST` | `/api/workspace/set` | 切换工作区 |
| `GET` | `/api/sessions/all` | 全部已注册工作区下的会话列表 |
| `POST` | `/api/session` | 创建 Session |
| `GET` | `/api/sessions` | 列出 Session |
| `DELETE` | `/api/session/{sid}` | 删除 Session |
| `GET` | `/api/session/{sid}/history` | 获取历史消息 |
| `POST` | `/api/session/{sid}/chat` | 启动 Agent，SSE 流式返回 |
| `GET` | `/api/session/{sid}/stream` | 断线重连 SSE |
| `GET` | `/api/session/{sid}/recover` | 恢复 Session 状态 |
| `GET` | `/api/status` | 全局运行状态 |
| `GET` | `/api/session/{sid}/status` | 全局运行状态（历史兼容） |
| `POST` | `/api/session/{sid}/respond` | 响应权限确认 |
| `GET` | `/api/session/{sid}/commits` | Git 快照列表 |
| `POST` | `/api/session/{sid}/checkout` | 回退到历史快照 |
| `POST` | `/api/session/{sid}/interrupt` | 中断 Agent |
| `GET` | `/api/metrics/llm/calls` | LLM 调用明细 |
| `GET` | `/api/metrics/llm/summary` | LLM 调用汇总 |
| `GET` | `/api/metrics/llm/dashboard` | LLM 仪表盘 |

## 核心架构

```
前端 (React + TypeScript)
  ↕ SSE（StreamEvent） + REST
FastAPI (app/)
  ↕
AgentRuntime (agent/runtime.py)         ← ReAct 主循环，多 Session 管理
  ↕
actions (agent/actions.py)              ← model_call / execute_one_tool
  ↕                    ↕
LangChain LLM         HookManager (shared/hooks.py)
(agent/llm_lc.py)     ├─ StreamDriverHook → SSE 广播
                      ├─ MetricsHook     → SQLite 指标
                      └─ LoggingHook     → 控制台输出
  ↕
Message (shared/types.py) ← 前后端唯一的消息类型（Pydantic）
  ↕
Workspace (agent/core/workspace.py) ← 路径管理 + I/O 代理
  ├─ run_shell()    临时子进程
  ├─ read_file()    Path 封装
  ├─ write_file()   Path 封装
  └─ resolve()      路径越界防护
```

### 关键设计

- **Message 唯一真相源**：同为后端存储、SSE 协议、前端渲染的数据载体。`msg[field] += delta` 字段名即协议。
- **Hook 系统**：BaseHook 12 个生命周期方法，HookManager 并行分发，单 hook 异常不影响主循环。
- **Tool 架构**：每个工具 = async handler + LangChain `StructuredTool.from_function()`，OpenAI schema 自动生成。17 个工具全局注册，按名分发。
- **Workspace 纯 I/O**：无状态，不持终端，不做安全检查。Shell 执行用 `asyncio.create_subprocess_shell` 临时子进程。
- **Session JSONL 持久化**：Message 同步顺序落盘，加载时兼容多种旧格式。
- **SubAgent 原地分发**：`execute_one_tool` 按名称识别 SubAgent/BrowserInspect，启动独立 ReAct 循环。

### SSE 事件流

```
message_start       → 新 Message 开始
chunk_delta         → msg[field] += delta（前端直接 +=）
chunk_complete      → 结构化字段一次性完成（tool_calls / tool_result）
message_finish      → Message 完成
turn_complete       → Turn 结束，含 token 统计
interrupted         → 中断通知
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | — | API 密钥（必填） |
| `LLM_BASE_URL` | — | API 端点（必填） |
| `LLM_MODEL_ID` | — | 模型 ID（必填） |
| `LLM_TIMEOUT` | `60` | 请求超时（秒） |
| `AGENT_WORKSPACE` | 当前目录 | 工作区路径 |
| `BROWSER_HEADLESS` | `1` | `0` 为有头模式 |
| `SERPAPI_KEY` | — | WebSearch 用 |
| `LLM_METRICS_DB_PATH` | `.byte_agent/ai_metrics.sqlite3` | 指标数据库 |
| `LLM_INPUT_COST_YUAN_PER_1M_TOKENS` | `3` | 输入成本 |
| `LLM_OUTPUT_COST_YUAN_PER_1M_TOKENS` | `6` | 输出成本 |

## Skill 扩展

```bash
mkdir -p backend/agent/skills/my_skill
vim backend/agent/skills/my_skill/SKILL.md
# 下一次 step 自动扫描并注入摘要到系统消息
```

也可通过 `SubAgent(with_skills=["my_skill"])` 在启动子智能体时直接注入。

## 调试

子智能体控制台输出（`agent/actions.py`）：

```python
_SUBAGENT_DEBUG = True   # 开启实时打印 subagent 流式输出
_SUBAGENT_DEBUG = False  # 关闭
```
