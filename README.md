# Byte E2E Agent

ReAct 智能体 + FastAPI 后端 + React (Vite) 前端。

## 项目结构

```
byte_e2e_agent/
├── start.sh                   # 一键启动前后端
├── docs/                      # 变更文档
├── backend/
│   ├── main.py                # FastAPI 入口 + 工作区 / Session / SSE API
│   ├── project.py             # 工作区、Session 与调度器编排
│   ├── README.md              # 后端说明入口
│   ├── .python-version        # Python 版本声明
│   ├── .env.example           # 环境变量模板
│   ├── pyproject.toml         # 依赖声明（uv 用）
│   ├── requirements.txt       # 依赖声明（pip 用）
│   ├── uv.lock                # uv 锁定文件
│   └── agent/
│       ├── llm.py             # LLM 客户端（OpenAI 兼容）
│       ├── scheduler.py       # 单例执行调度器与 ReAct 工具调用循环
│       ├── session.py         # Session 数据容器与 JSONL 持久化
│       ├── transcript.py      # 会话事件存储单元
│       ├── stream_channel.py  # SSE chunk / flush 广播通道
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
`./start.sh`
```

前后端同时启动，Ctrl+C 一键停止。可在任意目录执行。

### 3. 分别启动

**后端**

```bash
cd backend
uv sync                                   # uv 用户
`uv run uvicorn main:app --reload --port 8000`

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
- **Skill 系统** — Markdown 特化能力模块：`agent/skills/<name>/Skill.md`
- **PersistentTerminal** — 跨平台持久 Shell（`cd` 状态保留），`terminal_chunk` 流式推送
- **角色化消息协议** — `system → user → assistant → user(tool) → …` 标准对话链
- **json-repair** — LLM 输出格式小毛病自动修复，不浪费 token

## Skill 扩展

```bash
mkdir -p agent/skills/my_skill
vim agent/skills/my_skill/Skill.md
# 下一次模型 step 会重新扫描并注入
```

`Skill.md` 的第一段会作为摘要注入独立的 Skill context 系统消息；需要完整能力定义时，
Agent 通过 `LoadSkill` 读取完整内容。Skill context 会在每个模型 step 前刷新，因此支持热重载。

## 常用命令

```bash
./start.sh                                 # 一键启动
cd backend && uvicorn main:app --port 8000 # 后端生产
cd frontend && npm run build               # 前端构建
```
