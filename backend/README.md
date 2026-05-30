# Backend

ReAct 智能体运行时——FastAPI 应用层 + Agent 引擎。

## 项目结构

```
backend/
├── main.py                    # FastAPI app factory + uvicorn 入口
├── pyproject.toml             # 依赖声明（uv 管理）
├── requirements.txt           # 依赖声明（pip 兼容）
├── uv.lock                    # uv 锁定文件
├── .python-version            # Python 3.14
├── .env.example               # 环境变量模板
│
├── app/                       # FastAPI 应用层
│   ├── api/
│   │   ├── router.py          # 路由聚合
│   │   ├── sse.py             # SSE 响应辅助
│   │   └── routes/            # health / workspace / sessions / chat / metrics
│   ├── core/
│   │   ├── config.py          # Settings 单例
│   │   └── cors.py            # CORS 中间件
│   ├── schemas/               # Pydantic 请求模型
│   ├── services/
│   │   └── project.py         # Project 单例：workspace + session + scheduler 编排
│   └── dependencies.py        # FastAPI 依赖注入
│
└── agent/                     # Agent 引擎（与 FastAPI 解耦）
    ├── actions.py             # ReAct 原语：model_call / execute_one_tool / run_subagent
    ├── scheduler.py           # Scheduler 类：状态持有 + 循环编排
    ├── prompts.py             # 系统提示词
    ├── session.py             # Session 数据容器 + JSONL 持久化
    ├── sandbox.py             # 执行沙箱：终端 / 文件 / 编辑 / 路径安全
    ├── transcript.py          # TranscriptStream：SSE chunk/flush 事件系统
    ├── terminal.py            # PersistentTerminal：跨平台 PTY 持久 Shell
    ├── llm.py                 # HelloAgentsLLM：OpenAI 兼容异步客户端
    ├── shadow_repo.py         # ShadowRepo：基于 Dulwich 的工作区快照
    ├── metrics.py             # SQLite LLM 调用追踪（tokens / 延迟 / 成本）
    ├── tools/                 # 工具系统
    │   ├── base.py            # BaseTool 基类
    │   ├── toolset.py         # ToolSet：Pydantic → OpenAI schema 动态生成
    │   ├── subagent.py        # SubAgent 工具定义
    │   ├── shell.py           # Shell 工具（流式 + 可中断）
    │   ├── read.py / write.py / edit.py  # 文件操作
    │   ├── grep.py / glob.py  # 搜索
    │   ├── search.py          # WebSearch / WebFetch
    │   ├── pyrepl.py          # 安全 Python REPL
    │   ├── browser.py         # BrowserOpen / BrowserAct / BrowserInspect
    │   ├── skill.py           # Skill 扫描与 LoadSkill 工具
    │   └── task.py            # Task 管理：Rewrite / Update / List
    ├── skills/                # Skill Markdown 模块（15 个）
    ├── errors/                # InterruptedError / ToolMismatchError / 修复管线
    └── utils/                 # safety / sysguard / 终端样式
```

## 环境要求

| 工具 | 最低版本 | 检查 |
|------|---------|------|
| Python | 3.14 | `python --version` |
| uv | 0.5+ | `uv --version` |
| Chromium | — | Playwright 自动下载（见下文） |

## 快速开始

### 1. 安装依赖

```bash
cd backend
uv sync
```

### 2. 安装 Playwright 浏览器

BrowserInspect / BrowserOpen / BrowserAct 依赖 Playwright。首次使用需安装 Chromium：

```bash
uv run playwright install chromium
```

系统依赖（Linux 常见缺失项）：

```bash
# Debian / Ubuntu
sudo apt install libnss3 libnspr4 libatk-bridge2.0-0 libdrm2 \
  libxkbcommon0 libgbm1 libasound2t64

# Fedora
sudo dnf install nss nspr atk at-spi2-atk cups-libs libdrm \
  libxkbcommon libgbm alsa-lib
```

### 3. 有头模式（可选）

默认无头运行。需要看到浏览器窗口时，在 `.env` 中设置：

```bash
BROWSER_HEADLESS=0
```

需要有 X Server 或 Wayland（`echo $DISPLAY` 不为空）。

### 4. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，必填：
#   LLM_API_KEY     — API 密钥
#   LLM_BASE_URL    — API 端点
#   LLM_MODEL_ID    — 模型 ID
# 可选：
#   BROWSER_HEADLESS=0  — 有头模式
```

### 5. 启动

```bash
uv run uvicorn main:app --reload --port 8000
```

Swagger: `http://localhost:8000/docs`

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
| `GET` | `/api/session/{sid}/history` | 获取历史 |
| `POST` | `/api/session/{sid}/chat` | 启动 Agent，返回 SSE 流 |
| `GET` | `/api/session/{sid}/stream` | 断线重连 SSE |
| `GET` | `/api/session/{sid}/recover` | 恢复 Session 状态 |
| `POST` | `/api/session/{sid}/respond` | 响应权限确认 |
| `GET` | `/api/session/{sid}/commits` | Shadow 提交列表 |
| `POST` | `/api/session/{sid}/checkout` | 回退到历史 Commit |
| `POST` | `/api/session/{sid}/interrupt` | 中断当前执行 |
| `GET` | `/api/metrics/llm/calls` | LLM 调用明细 |
| `GET` | `/api/metrics/llm/summary` | LLM 调用汇总 |
| `GET` | `/api/metrics/llm/dashboard` | LLM 仪表盘 |

## 核心架构

### 分层

```
app/     — FastAPI 路由 + schema + 依赖注入
agent/   — 纯逻辑，不依赖 FastAPI
  actions.py  — 无状态原语（model_call / execute_one_tool / run_subagent）
  scheduler.py — 有状态编排（持有 _current_session + _interrupt_event）
  tools/      — 工具定义（Pydantic → OpenAI schema 自动生成）
```

### ReAct 循环

```
user message → _query_loop:
  ├─ 构建 messages = [system prompts..., history...]
  ├─ model_call(llm_client, session_id, channel, messages, tools)
  │    └─ HelloAgentsLLM.think_stream() → chunk → TranscriptStream → SSE
  ├─ flush assistant transcript → 持久化
  ├─ finish_reason == "stop" → shadow snapshot → 结束
  └─ 遍历 tool_calls → execute_one_tool()
       ├─ 普通工具 → action.execute()
       └─ SubAgent / BrowserInspect → run_subagent() 原地分发
```

### 关键设计决策

- **ToolSet 动态 schema**：Pydantic model → `$defs` 内联 → OpenAI function definition，新增工具零摩擦
- **TranscriptStream**：唯一事件源，chunk 逐步构建 message + 广播 SSE，flush 收尾
- **subscribe-before-start**：先订阅 SSE 队列，再启动 Scheduler，零事件丢失
- **PersistentTerminal**：PTY 持久 bash 进程，`cd` 状态跨命令保留
- **ShadowRepo**：Dulwich bare repo，每次用户消息后自动快照，支持回退和 diff
- **Session JSONL 持久化**：同步顺序落盘，加载时运行修复管线处理中断残留
- **三层安全**：命令字符串预检 → Landlock 内核沙箱 → 路径越界审查
- **SubAgent 原地分发**：`execute_one_tool` 通过 `isinstance` 识别 SubAgent/BrowserInspect 并直接调用 `run_subagent`，不经过工具自身的 `execute()`

## Skill 系统

Skills 放在 `agent/skills/<name>/SKILL.md`。模型每轮会收到可用 Skill 摘要，按需调用 `LoadSkill` 读取完整内容。

```bash
mkdir -p backend/agent/skills/my_skill
vim backend/agent/skills/my_skill/SKILL.md
# 下一次 step 自动扫描并注入
```

也可通过 `SubAgent(with_skills=["my_skill"])` 在启动时直接注入。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | — | API 密钥（必填） |
| `LLM_BASE_URL` | — | API 端点（必填） |
| `LLM_MODEL_ID` | — | 模型 ID（必填） |
| `LLM_TIMEOUT` | `60` | 请求超时（秒） |
| `AGENT_WORKSPACE` | 项目根目录 | 工作区路径 |
| `BROWSER_HEADLESS` | `1` | `0` 为有头模式 |
| `SERPAPI_KEY` | — | WebSearch 用 |
| `LLM_METRICS_DB_PATH` | `.tmp/ai_metrics.sqlite3` | 指标数据库 |
| `LLM_INPUT_COST_YUAN_PER_1M_TOKENS` | `3` | 输入成本 |
| `LLM_OUTPUT_COST_YUAN_PER_1M_TOKENS` | `6` | 输出成本 |

## 调试

子智能体控制台输出：

```python
# agent/actions.py
_SUBAGENT_DEBUG = True   # 开启：控制台实时打印 subagent 流式输出
_SUBAGENT_DEBUG = False  # 关闭
```
