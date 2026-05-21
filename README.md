# Byte E2E Agent

FastAPI 后端 + React (Vite) 前端。内含 ReAct 智能体模块，通过独立 CLI 启动。

## 项目结构

```
byte_e2e_agent/
├── start.sh                  # 一键启动前后端
├── backend/
│   ├── main.py               # FastAPI 入口（Hello World 端点）
│   ├── cli.py                # ReAct 智能体交互式 CLI
│   ├── pyproject.toml        # 依赖声明（uv 用）
│   ├── requirements.txt      # 依赖声明（pip 用，由 uv export 生成）
│   ├── .env.example          # 环境变量模板
│   └── agent/                # ReAct 智能体模块
│       ├── llm.py            # LLM 客户端（OpenAI 兼容）
│       ├── react.py          # ReAct 循环 + Prompt 模板
│       ├── plan_manager.py   # 计划状态机
│       ├── terminal.py       # 持久 Shell 会话
│       └── tools/            # 工具集（Shell/Read/Write/Edit/Search/SubTask）
├── frontend/
│   ├── src/App.jsx           # 页面组件
│   └── vite.config.js        # 含 /api 开发代理
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

前后端同时启动，Ctrl+C 一键停止。可在任意目录执行此脚本。

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

独立于前后端框架的交互式智能体：

```bash
cd backend
uv run python cli.py            # uv 用户
python cli.py                   # venv / pip 用户（需先激活环境）
```

进入交互界面后直接输入问题即可。支持命令：

| 命令 | 说明 |
|------|------|
| `/clear` | 清空对话上下文 |
| `/exit` | 退出 |
| `Ctrl+C` | 退出 |

## API 端点（FastAPI）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | Hello World |
| `GET` | `/api/hello` | Hello World（含 status） |
| `POST` | `/api/agent/stream` | SSE 流式 Agent |

## 开发代理说明

Vite 开发服务器将 `/api/*` 代理到 `localhost:8000`，前端可直接写 `fetch("/api/hello")`。

## 常用命令

```bash
# 一键启动
./start.sh

# 后端 — 生产运行
cd backend && uvicorn main:app --host 0.0.0.0 --port 8000

# 前端 — 生产构建
cd frontend && npm run build
npm run preview
```
