# Backend Refactor: Hook-Driven Architecture

> 对标 `byte_e2e_agent_rs/src/core/` 的模块化设计 + LangChain callback 模式

## 1. 设计目标

### 现状问题

| 问题 | 具体表现 |
|------|---------|
| `session.py` 臃肿 | 578 行，混合 Session 类 + 持久化 + 消息构建 + transcript 管理 |
| 无显式状态机 | `scheduler._state` 是字符串 `"idle"` / `"running"` / `"awaiting_input"` |
| 路径散落 | session 目录、DB 路径、task JSON 路径散落在模块级函数 |
| 无 Hook 体系 | metrics 硬编码在 `llm.py` 的 `finally` 块；SSE 推送和 transcript 耦合 |
| 类型分散 | Transcript / StreamEvent 定义在 `transcript.py`，LLM 事件在 `llm.py` |

### 目标

```
┌─────────────────────────────────────────────────────────┐
│                    AgentRuntime                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  主循环 (owns state)                               │  │
│  │  • messages[]       — 消息列表，主循环构建/修复    │  │
│  │  • error handling   — try/except 全程在主循环      │  │
│  │  • turn 编排        — model_call → tools → repeat  │  │
│  └──────────────────────┬────────────────────────────┘  │
│                         │ lifecycle events              │
│  ┌──────────────────────▼────────────────────────────┐  │
│  │               HookManager                         │  │
│  │  ┌──────────────────────────────────────────────┐ │  │
│  │  │ StreamDriverHook  ────▶ SSE → Frontend        │ │  │
│  │  │ MetricsHook       ────▶ SQLite                │ │  │
│  │  │ LoggingHook       ────▶ Console               │ │  │
│  │  │ CustomHook        ────▶ user-defined          │ │  │
│  │  └──────────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**核心原则：**

1. **主循环拥有 state** — messages 和 errors 由 `AgentRuntime` 主循环维护，不在 hook 中
2. **Hook 只收通知** — metrics、logging、SSE 推送等副作用由 hook 分发
3. **Hook 抛异常不影响主循环** — 每个 hook 独立 try/catch
4. **完全照抄 LangChain** — `BaseHook` + `HookManager` 接口对齐 `BaseCallbackHandler` + `CallbackManager`

---

## 2. 目录结构对比

### 当前

```
agent/
├── actions.py             # model_call, execute_one_tool, run_subagent (333行)
├── llm.py                 # LLM 客户端 (硬编码 metrics)
├── metrics.py             # SQLite 指标存储
├── prompts.py             # 系统提示词 (214行)
├── sandbox.py             # Sandbox (terminal + browser)
├── scheduler.py           # Scheduler 单例 (319行)
├── session.py             # Session + 持久化 (578行) ← 太胖
├── shadow_repo.py         # Git 快照
├── terminal.py            # PersistentTerminal
├── transcript.py          # Transcript + TranscriptStream
├── errors/                # 错误类型
├── skills/                # 14 个 skill 模块
├── tools/                 # 15 个工具文件
└── utils/                 # 工具函数
```

### 目标（对标 Rust `src/core/`）

```
agent/
├── core/                         # 🆕 核心抽象
│   ├── __init__.py               # 公开 API
│   ├── types.py                  # Turn, Message, MessageChunk, ChunkKind, StreamEvent
│   ├── config.py                 # AgentConfig, ToolSet 枚举, AccessPolicy
│   ├── workspace.py              # Workspace 路径管理
│   ├── prompts.py                # 系统提示词（从 agent/prompts.py 迁入）
│   └── hooks.py                  # 🆕 BaseHook + HookManager
│
├── session/                      # 🆕 拆分 session.py → 3 文件
│   ├── __init__.py
│   ├── config.py                 # SessionConfig（不可变配置）
│   ├── entry.py                  # SessionEntry（运行时聚合）
│   └── status.py                 # SessionStatus 状态机 + RuntimeStatus
│
├── hook/                         # 🆕 内置 Hook 实现
│   ├── __init__.py
│   ├── stream_driver.py          # StreamDriverHook → SSE 推送
│   ├── metrics_hook.py           # MetricsHook → SQLite 指标
│   └── logging_hook.py           # LoggingHook → 彩色控制台输出
│
├── task/                         # 🆕 任务管理独立
│   ├── __init__.py
│   ├── types.py                  # Task / TaskStatus
│   ├── manager.py                # load / save / reconstruct
│   └── tools.py                  # TaskListTool / TaskRewriteTool / TaskUpdateTool
│
├── persistence/                  # 🆕 持久化层
│   ├── __init__.py
│   ├── db.py                     # Database (SQLite)
│   └── schema.py                 # DB schema
│
├── runtime.py                    # 🆕 AgentRuntime（替代 scheduler.py）
│
├── tools/                        # ✅ 保持不变
├── sandbox.py                    # ✅ 保持不变
├── llm.py                        # ✅ 去掉 metrics_store → 交给 MetricsHook
├── terminal.py                   # ✅ 保持不变
├── shadow_repo.py                # ✅ 保持不变
├── errors/                       # ✅ 保持不变
├── skills/                       # ✅ 保持不变
└── utils/                        # ✅ 保持不变
```

---

## 3. Hook 体系（完全照抄 LangChain）

### 3.1 BaseHook

对标 `langchain.callbacks.base.BaseCallbackHandler`：

```python
class BaseHook(ABC):
    """所有 Hook 的基类。每个方法默认 no-op，子类按需重写。"""

    # ══ LLM 生命周期 ═══════════════════════════════════════

    async def on_llm_start(
        self, *,
        messages: list[dict],
        tools: list[dict] | None,
        turn_id: str,
        message_id: str,
        **kwargs,
    ) -> None:
        """LLM 调用开始"""

    async def on_llm_new_token(
        self, *,
        token: str,
        kind: ChunkKind,        # Reasoning | Text | ToolCall
        message_id: str,
        chunk_id: str,
        tool_name: str | None,
        **kwargs,
    ) -> None:
        """收到一个流式 token"""

    async def on_llm_end(
        self, *,
        finish_reason: str,
        usage: dict | None,     # {prompt_tokens, completion_tokens, total_tokens}
        message_id: str,
        turn_id: str,
        latency_ms: int,
        **kwargs,
    ) -> None:
        """LLM 调用完成"""

    async def on_llm_error(
        self, *,
        error: Exception,
        message_id: str,
        **kwargs,
    ) -> None:
        """LLM 调用出错"""

    # ══ Tool 生命周期 ═══════════════════════════════════════

    async def on_tool_start(
        self, *,
        tool_name: str,
        tool_args: dict,
        tool_call_id: str,
        **kwargs,
    ) -> None:
        """工具开始执行"""

    async def on_tool_end(
        self, *,
        tool_name: str,
        output: str,
        tool_call_id: str,
        is_error: bool,
        **kwargs,
    ) -> None:
        """工具执行完成"""

    async def on_tool_error(
        self, *,
        tool_name: str,
        error: Exception,
        tool_call_id: str,
        **kwargs,
    ) -> None:
        """工具执行出错"""

    # ══ Turn 生命周期 ═══════════════════════════════════════

    async def on_turn_start(
        self, *,
        turn_id: str,
        session_id: str,
        user_question: str,
        **kwargs,
    ) -> None:
        """一个 Turn 开始（用户发送消息）"""

    async def on_turn_end(
        self, *,
        turn_id: str,
        session_id: str,
        input_tokens: int,
        output_tokens: int,
        **kwargs,
    ) -> None:
        """一个 Turn 结束"""

    # ══ SubAgent 生命周期 ═══════════════════════════════════

    async def on_subagent_start(
        self, *,
        task: str,
        parent_session_id: str,
        max_steps: int,
        **kwargs,
    ) -> None:
        """子智能体启动"""

    async def on_subagent_end(
        self, *,
        result: str,
        **kwargs,
    ) -> None:
        """子智能体完成"""
```

### 3.2 HookManager

对标 `langchain.callbacks.manager.CallbackManager`：

```python
class HookManager:
    """管理多个 Hook 实例，并行分发事件。

    设计要点：
    - 每个 hook 的调用是独立的 asyncio task
    - 单个 hook 抛异常不影响其他 hook 和主循环
    - dispatch() 非阻塞（fire-and-forget），但提供 flush() 等待全部完成
    """

    def __init__(self, hooks: list[BaseHook] | None = None): ...
    def add_hook(self, hook: BaseHook) -> None: ...
    def remove_hook(self, hook: BaseHook) -> None: ...

    async def dispatch(self, method: str, **kwargs) -> None:
        """并行调用所有 hook 的指定方法。单个失败不影响其他。"""

    async def flush(self) -> None:
        """等待所有 pending dispatch 完成。用于 turn 边界确保事件顺序。"""
```

### 3.3 内置 Hook 实现

| Hook | 实现的方法 | 职责 |
|------|-----------|------|
| `StreamDriverHook` | `on_llm_new_token`, `on_tool_end`, `on_turn_start`, `on_turn_end` | 构建 StreamEvent 推送给 SSE 订阅者 |
| `MetricsHook` | `on_llm_end` | 记录 LLM 调用指标到 SQLite |
| `LoggingHook` | 所有方法 | 彩色控制台输出（`dim`/`info`/`success`/`error`） |

### 3.4 数据流

```
用户发消息
  │
  ▼
AgentRuntime.invoke_user(session, question)
  │
  ├─▶ HookManager.dispatch("on_turn_start", ...)
  │     ├─ StreamDriverHook  → SSE: turn_start
  │     └─ LoggingHook       → print: "Turn started"
  │
  ▼
_execute_turn(session)   ← 主循环
  │
  ├─ for step in max_steps:
  │    │
  │    ├─▶ HookManager.dispatch("on_llm_start", ...)
  │    │
  │    ├─ for token in llm.think_stream():     ← 流式 LLM
  │    │     │
  │    │     ├─ 主循环: 累积 token 到 message.content / tool_calls
  │    │     │
  │    │     └─▶ HookManager.dispatch("on_llm_new_token", ...)
  │    │           ├─ StreamDriverHook  → SSE: chunk delta
  │    │           └─ (MetricsHook 不关心单个 token)
  │    │
  │    ├─▶ HookManager.dispatch("on_llm_end", ...)
  │    │     ├─ StreamDriverHook  → SSE: message_finish
  │    │     └─ MetricsHook       → SQLite: record_call()
  │    │
  │    ├─ for each tool_call:
  │    │     ├─▶ HookManager.dispatch("on_tool_start", ...)
  │    │     ├─ execute_tool()   ← 主循环执行
  │    │     └─▶ HookManager.dispatch("on_tool_end", ...)
  │    │           └─ StreamDriverHook  → SSE: tool_result
  │    │
  │    └─ if finish_reason == "stop": break
  │
  ├─▶ HookManager.dispatch("on_turn_end", ...)
  │     ├─ StreamDriverHook  → SSE: turn_complete
  │     └─ LoggingHook       → print: "Turn done"
  │
  └─▶ HookManager.flush()   ← 确保所有事件已发出
```

---

## 4. 模块设计

### 4.1 `core/types.py` — 核心类型

```python
# 对标 Rust types.rs

class ChunkKind(Enum):
    REASONING = "reasoning"     # 推理过程（灯泡图标）
    TEXT = "text"               # 普通文本
    TOOL_CALL = "tool_call"     # 工具调用（函数名 + JSON 参数）
    TOOL_RESULT = "tool_result" # 工具执行结果

@dataclass
class ChunkMetadata:
    tool_name: str | None = None
    tool_args: str | None = None
    is_error: bool = False

@dataclass
class MessageChunk:
    id: str              # chunk_id（tool_call 用 internal_call_id）
    kind: ChunkKind
    content: str         # 流式时部分，完成时完整
    metadata: ChunkMetadata

@dataclass
class Message:
    id: str
    turn_id: str
    seq: int
    role: MessageRole    # User | Assistant | Reasoning | ToolCall | ToolResult
    status: MessageStatus # Streaming | Complete
    chunks: list[MessageChunk]

class StreamEvent(Enum):
    """StreamDriver → App 层的旁路事件"""
    MESSAGE_START = "message_start"
    CHUNK_DELTA = "chunk_delta"
    CHUNK_COMPLETE = "chunk_complete"
    MESSAGE_FINISH = "message_finish"
    TURN_COMPLETE = "turn_complete"
    INTERRUPTED = "interrupted"
```

### 4.2 `core/hooks.py` — Hook 接口

见第 3 节。

### 4.3 `core/workspace.py` — 路径管理

```python
# 对标 Rust workspace.rs
# 散落在 session.py 的 _session_dir / _messages_path / _save_transcript_sync 全部收拢

@dataclass
class Workspace:
    root: Path          # 工作区根目录

    def agent_dir(self) -> Path: ...        # {root}/.byte_agent/
    def sessions_dir(self) -> Path: ...     # {root}/.byte_agent/sessions/
    def session_dir(self, sid: str) -> Path: ...  # {root}/.byte_agent/sessions/{sid}/
    def session_db_path(self, sid: str) -> Path: ...
    def session_config_path(self, sid: str) -> Path: ...
    def tasks_path(self, sid: str) -> Path: ...
    def ensure_dirs(self, sid: str) -> None: ...
```

### 4.4 `session/` — 三件套

| 文件 | 对标 Rust | 职责 |
|------|----------|------|
| `config.py` | `session/config.rs` | `SessionConfig` — 不可变配置（name, model_id, tool_set, skills, rules, access） |
| `status.py` | `session/status.rs` | `SessionStatus` 状态机 + `RuntimeStatus` |
| `entry.py` | `session/entry.rs` | `SessionEntry` — 运行时聚合（id + config + status + db + llm_client） |

```python
# session/status.py
class SessionStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PENDING = "pending"       # 等待子 session 返回
    INTERRUPTED = "interrupted"

    def is_invokable(self) -> bool: ...
    def is_busy(self) -> bool: ...

# session/config.py
@dataclass(frozen=True)
class SessionConfig:
    name: str
    model_id: str
    preamble: str
    tool_set: ToolSet
    preloaded_skills: list[str]
    rules: list[str]
    access: AccessPolicy
```

### 4.5 `hook/stream_driver.py` — SSE 推送

```python
# 对标 Rust hook/stream_driver.rs
# 替代当前 transcript.py 的 TranscriptStream

class StreamDriverHook(BaseHook):
    """纯发送器：将 StreamEvent 推入 asyncio.Queue，供 SSE endpoint 消费。

    对标 Rust: 不持有 ID 状态，所有 ID 由主循环显式传入。
    """

    def __init__(self):
        self._subscribers: list[asyncio.Queue[StreamEvent | None]] = []

    def subscribe(self) -> asyncio.Queue[StreamEvent | None]: ...
    def unsubscribe(self, q) -> None: ...
    def close(self) -> None: ...

    # BaseHook 实现
    async def on_llm_new_token(self, **kwargs) -> None:
        """发送 CHUNK_DELTA"""
    async def on_tool_end(self, **kwargs) -> None:
        """发送 TOOL_RESULT Message"""
    async def on_turn_start(self, **kwargs) -> None:
        """发送 user_question Message"""
    async def on_turn_end(self, **kwargs) -> None:
        """发送 TURN_COMPLETE"""
```

### 4.6 `runtime.py` — AgentRuntime

```python
# 对标 Rust runtime.rs
# 替代 agent/scheduler.py

class AgentRuntime:
    """Per-Project 执行运行时。

    一次只允许一个 Session 在 Running 状态。
    """

    def __init__(
        self,
        workspace: Workspace,
        hook_manager: HookManager | None = None,
    ): ...

    @property
    def status(self) -> RuntimeStatus: ...

    # ── Session 管理 ──
    def create_session(self, config: SessionConfig) -> SessionEntry: ...
    def get_session(self, session_id: str) -> SessionEntry | None: ...
    def list_sessions(self) -> list[str]: ...

    # ── Invoke ──
    async def invoke_user(
        self,
        session: SessionEntry,
        question: str,
        max_steps: int = 50,
    ) -> str: ...

    async def invoke_agent(
        self,
        caller_id: str,
        target_id: str,
        task: str,
        max_turns: int | None = None,
    ) -> str: ...

    # ── 内部 ──
    async def _execute_turn(
        self,
        session: SessionEntry,
        question: str,
        max_steps: int,
    ) -> None:
        """主循环。拥有 messages 和 errors 的完整所有权。"""
```

---

## 5. 迁移计划

### Phase 1: 核心抽象（零破坏）

**新文件：**
- `agent/core/__init__.py`
- `agent/core/types.py`
- `agent/core/hooks.py` — `BaseHook` + `HookManager`
- `agent/core/config.py` — `AgentConfig`, `ToolSet`, `AccessPolicy`
- `agent/core/workspace.py`

**验证：** `python -c "from agent.core import BaseHook, HookManager, Workspace"` 通过

### Phase 2: Session 拆分

**新文件：**
- `agent/session/config.py` — 从 `session.py` 提取配置
- `agent/session/status.py` — 状态机
- `agent/session/entry.py` — 运行时聚合

**旧文件：** `agent/session.py` → 保留为兼容层（re-export）

**验证：** 现有 API 不变，Session 创建方式兼容

### Phase 3: 内置 Hook

**新文件：**
- `agent/hook/__init__.py`
- `agent/hook/stream_driver.py` — `StreamDriverHook`
- `agent/hook/metrics_hook.py` — `MetricsHook`
- `agent/hook/logging_hook.py` — `LoggingHook`

**验证：** Hook 独立可测，不依赖 Runtime

### Phase 4: Runtime 替代 Scheduler

**新文件：**
- `agent/runtime.py` — `AgentRuntime`

**旧文件：**
- `agent/scheduler.py` → 保留为别名（deprecated）
- `agent/actions.py` → 核心函数迁入 `runtime.py` 或 `_engine.py`
- `agent/transcript.py` → `TranscriptStream` 迁入 `hook/stream_driver.py`

**验证：** 端到端测试通过，SSE 正常推送

### Phase 5: Task + Persistence 独立

**新文件：**
- `agent/task/__init__.py`, `types.py`, `manager.py`, `tools.py`
- `agent/persistence/__init__.py`, `db.py`, `schema.py`

**验证：** Task 工具和持久化正常工作

---

## 6. 不变部分

以下模块在重构中 **保持不变**（仅 import 路径可能调整）：

- `agent/tools/` — 15 个工具文件，接口不变
- `agent/sandbox.py` — Sandbox (terminal + browser)
- `agent/llm.py` — `HelloAgentsLLM`（去掉硬编码的 metrics_store 参数）
- `agent/terminal.py` — `PersistentTerminal`
- `agent/shadow_repo.py` — Git 快照
- `agent/errors/` — 错误类型
- `agent/skills/` — 14 个 skill 模块
- `agent/utils/` — 工具函数
- `app/` — FastAPI 层（仅调整 import 路径）

---

## 7. 文件大小预估

| 文件 | 行数 | 说明 |
|------|------|------|
| `core/types.py` | ~120 | 纯类型定义 |
| `core/hooks.py` | ~150 | BaseHook + HookManager |
| `core/config.py` | ~80 | AgentConfig + ToolSet |
| `core/workspace.py` | ~100 | 路径管理 |
| `session/config.py` | ~80 | SessionConfig |
| `session/status.py` | ~60 | 状态机 |
| `session/entry.py` | ~50 | SessionEntry |
| `hook/stream_driver.py` | ~150 | StreamDriverHook |
| `hook/metrics_hook.py` | ~60 | MetricsHook |
| `hook/logging_hook.py` | ~80 | LoggingHook |
| `runtime.py` | ~350 | AgentRuntime 主循环 |
| `task/types.py` | ~40 | Task / TaskStatus |
| `task/manager.py` | ~80 | load/save/reconstruct |
| `task/tools.py` | ~100 | TaskList/Rewrite/Update |
| `persistence/db.py` | ~80 | SQLite |
| `persistence/schema.py` | ~40 | Schema |

> 最大单文件从 578 行 (session.py) 降到 ~350 行 (runtime.py)，所有模块 < 200 行。
