# Byte E2E Agent

ReAct 智能体 + FastAPI 后端 + React (Vite) 前端。

## 项目结构

```
byte_e2e_agent/
├── start.sh                   # 一键启动前后端
├── docs/                      # 变更文档
├── backend/
│   ├── main.py                # FastAPI 入口 + SSE 流式 Agent 端点
│   ├── cli.py                 # ReAct 智能体交互式 CLI
│   ├── pyproject.toml         # 依赖声明（uv 用）
│   ├── requirements.txt       # 依赖声明（pip 用）
│   ├── .env.example           # 环境变量模板
│   └── agent/
│       ├── utils/             # 工具模块（JSON 修复、终端 ANSI）
│       ├── skills/            # Skill 可插拔知识模块
│       ├── tools/             # 工具系统（Shell/Read/Write/Edit/Search/…）
│       │   └── toolset.py     # 动态工具集（替代硬编码 Union）
│       ├── llm.py             # LLM 客户端（OpenAI 兼容）
│       ├── react.py           # ReAct 循环 + 角色化消息协议
│       ├── plan_manager.py    # 计划状态机
│       └── terminal.py        # 持久 Shell 会话（跨平台 PIPE）
├── frontend/
│   ├── src/
│   │   ├── App.jsx            # 入口
│   │   ├── components/        # StepCard / ToolRenderers / AgentDemo
│   │   └── hooks/             # useAgentStream（SSE 消费 + 状态管理）
│   └── vite.config.js         # 含 /api 开发代理
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

## ReAct 智能体 CLI

```bash
cd backend
uv run python cli.py            # uv 用户
python cli.py                   # venv / pip 用户
```

| 命令 | 说明 |
|------|------|
| `/clear` | 清空对话上下文 |
| `/exit` | 退出 |

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | Hello World |
| `GET` | `/api/hello` | Hello World |
| `POST` | `/api/agent/stream` | SSE 流式 Agent（事件：thinking / action / tool_call / terminal_chunk / finish） |

## 核心架构

- **ToolSet** — 运行时动态生成 Pydantic 鉴别联合，工具可热插拔
- **Skill 系统** — `agent/skills/<name>/Skill.md`，重启自动发现
- **PersistentTerminal** — 跨平台持久 Shell（`cd` 状态保留），`terminal_chunk` 流式推送
- **角色化消息协议** — `system → user → assistant → user(tool) → …` 标准对话链
- **json-repair** — LLM 输出格式小毛病自动修复，不浪费 token

## Skill 扩展

```bash
mkdir -p agent/skills/my_skill
vim agent/skills/my_skill/Skill.md
# 重启服务即生效
```

## 常用命令

```bash
./start.sh                                 # 一键启动
cd backend && uvicorn main:app --port 8000 # 后端生产
cd frontend && npm run build               # 前端构建
```
