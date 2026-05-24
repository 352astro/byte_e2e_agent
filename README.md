# Byte E2E Agent

ReAct 智能体 + FastAPI 后端 + React (Vite) 前端。

## 项目结构

```
byte_e2e_agent/
├── start.sh                   # 一键启动前后端
├── docs/                      # 变更文档
├── backend/
│   ├── main.py                # FastAPI app factory 与 uvicorn 入口
│   ├── README.md              # 后端说明入口
│   ├── .python-version        # Python 版本声明
│   ├── .env.example           # 环境变量模板
│   ├── pyproject.toml         # 依赖声明（uv 用）
│   ├── requirements.txt       # 依赖声明（pip 用）
│   ├── uv.lock                # uv 锁定文件
│   ├── app/                   # FastAPI 应用层（API / 配置 / schema / service）
│   │   ├── api/
│   │   │   ├── router.py      # 路由聚合
│   │   │   ├── sse.py         # SSE 响应辅助函数
│   │   │   └── routes/        # health / workspace / sessions / chat
│   │   ├── core/              # 配置与 CORS
│   │   ├── schemas/           # 请求模型
│   │   ├── services/
│   │   │   └── project.py     # 工作区、Session 与调度器编排
│   │   └── dependencies.py    # FastAPI 依赖注入
│   └── agent/
│       ├── llm.py             # LLM 客户端（OpenAI 兼容）
│       ├── scheduler.py       # 单例执行调度器与 ReAct 工具调用循环
│       ├── session.py         # Session 数据容器与 JSONL 持久化
│       ├── transcript.py      # Transcript 存储单元 + SSE chunk / flush 完成器
│       ├── sandbox.py         # 工作区沙箱、路径安全与工具执行分流
│       ├── terminal.py        # 持久 Shell 会话（跨平台 PIPE）
│       ├── tools/             # 工具系统（Shell/Read/Write/Edit/Search/…）
│       │   ├── toolset.py     # OpenAI tools schema 动态生成
│       │   ├── task.py        # 任务列表上下文与任务更新工具
│       │   ├── subtask.py     # 子任务工具
│       │   └── skill.py       # Skill 扫描与加载工具
│       ├── skills/            # Skill 特化能力模块
│       │   └── git_commit_skill/
│       │       └── Skill.md
│       └── utils/
│           ├── safety.py      # 路径与命令安全检查
│           └── _term.py       # 终端文本样式工具
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── main.tsx           # React 入口
│   │   ├── App.tsx            # 应用入口组件
│   │   ├── components/        # AgentDemo / Markdown / SessionSidebar
│   │   └── hooks/             # useAgentStream（SSE 消费 + 状态管理）
│   ├── package.json
│   └── vite.config.ts         # 含 /api 开发代理
└── .gitignore
```

## 环境要求

| 工具 | 最低版本 | 检查命令 |
|------|----------|----------|
| Python | 3.14 | `python --version` |
| Node.js | 20 | `node --version` |
| npm | 10 | `npm --version` |

## 快速开始

### 1. 配置环境变量

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入 LLM_API_KEY 等必填项
```

### 2. 一键启动（推荐）

```bash
./start.sh
```

前后端同时启动，Ctrl+C 一键停止。可在任意目录执行。

### 3. 分别启动

**后端**

```bash
cd backend
uv sync                                   # uv 用户
uv run uvicorn main:app --reload --port 8000

# 或 pip 用户：
python3.14 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**前端**

```bash
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173`。`http://localhost:8000/docs` 查看 Swagger。

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | Hello World |
| `GET` | `/api/hello` | Hello World |
| `GET` | `/api/workspace` | 当前工作区 |
| `POST` | `/api/workspace/set` | 切换工作区 |
| `POST` | `/api/session` | 创建 Session |
| `GET` | `/api/sessions` | 列出 Session |
| `DELETE` | `/api/session/{sid}` | 删除 Session |
| `GET` | `/api/session/{sid}/history` | 获取历史记录 |
| `POST` | `/api/session/{sid}/chat` | 启动 Agent 并返回 SSE |
| `GET` | `/api/session/{sid}/stream` | 断线重连 / 追赶 SSE |
| `GET` | `/api/session/{sid}/recover` | 恢复 Session 状态 |
| `POST` | `/api/session/{sid}/respond` | 响应权限确认等等待项 |

## 核心架构

- **FastAPI 应用层** — `app/` 承载路由、schema、配置、依赖注入和 Project service
- **Agent 运行时** — `agent/` 承载 Scheduler、Session、Sandbox、ToolSet、Transcript
- **ToolSet** — 运行时生成 OpenAI tools schema，支持嵌套 schema 内联和工具热插拔
- **Skill 系统** — Markdown 特化能力模块：`agent/skills/<name>/Skill.md`
- **StreamTranscriptCompletion** — 统一管理 SSE `chunk` / `flush` 与 `sub_streams`
- **PersistentTerminal** — 跨平台持久 Shell（`cd` 状态保留），Shell 输出通过 SSE 流式推送
- **角色化消息协议** — `system → user → assistant(tool_calls) → tool → …` 标准对话链
- **Session 持久化** — Transcript 顺序落盘，并在加载旧历史时修复孤立 tool 结果

## Skill 扩展

```bash
mkdir -p backend/agent/skills/my_skill
vim backend/agent/skills/my_skill/Skill.md
# 下一次模型 step 会重新扫描并注入
```

`Skill.md` 的第一段会作为摘要注入独立的 Skill context 系统消息；需要完整能力定义时，
Agent 通过 `LoadSkill` 读取完整内容。Skill context 会在每个模型 step 前刷新，因此支持热重载。

## 常用命令

```bash
./start.sh                                 # 一键启动
cd backend && uv run uvicorn main:app --port 8000 # 后端生产
cd frontend && npm run build               # 前端构建
```
