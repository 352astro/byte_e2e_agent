# 2026-05-22 — Sandbox 多会话隔离 + 全异步重构

## 动机

1. **全局状态阻止多会话**：`terminal.py` 和 `workspace.py` 的模块级单例
   导致所有 agent 实例共享同一个终端和工作目录。
2. **同步阻塞不适用于服务端**：`subprocess.Popen` + `select` 的同步流式读取
   在 FastAPI async 上下文中通过线程池执行，效率低下。

## 变更

### 新增

| 文件 | 说明 |
|------|------|
| `agent/sandbox.py` | `Sandbox` 类 — 终端管理、路径审查、危险指令拦截、工具执行分流 |

### 删除

| 删除项 | 原位置 |
|--------|--------|
| `set_terminal()` / `get_terminal()` / `reset_terminal()` | `agent/terminal.py` |
| `set_workspace_root()` / `get_workspace_root()` | `agent/tools/workspace.py` |

### 修改

| 文件 | 变更 |
|------|------|
| `agent/terminal.py` | 去除全局单例，精简注释 |
| `agent/llm.py` | `OpenAI` → `AsyncOpenAI`；`think_stream()` / `think()` → async |
| `agent/tools/base.py` | `execute()` → `async def execute(self, sandbox=None)` |
| `agent/tools/shell.py` | 委托 `sandbox.run_shell()` |
| `agent/tools/read.py` | 委托 `sandbox.read_file()` |
| `agent/tools/write.py` | 委托 `sandbox.write_file()` |
| `agent/tools/edit.py` | 委托 `sandbox.edit_file()`，保留 `_fuzzy_replace` 等 helper |
| `agent/tools/search.py` | `execute()` → async |
| `agent/tools/skill.py` | `execute()` → async |
| `agent/react.py` | `run()` / `run_stream()` → async；持有 Sandbox 实例；工具分流逻辑内联 |
| `main.py` | SSE endpoint → async generator；创建 Sandbox 传入 agent |
| `cli.py` | `asyncio.run(async_main())` 包装 |

### 不变

- `finish.py`、`plan.py`、`subtask.py` — 无 execute()，由 react 直接处理
- `_safety.py`、`_json.py`、`plan_manager.py`、`toolset.py` — 被 Sandbox 或 react 调用
- 前端 — 零改动

## 架构对比

```
旧（全局单例）                    新（实例隔离）
─────────────────────          ─────────────────────
workspace_root (global)        sandbox.workspace (per agent)
terminal (global)              sandbox.terminal (per agent)
Bash.execute() → terminal     Shell.execute(sandbox) → sandbox.run_shell()
Read.execute() → workspace    Read.execute(sandbox) → sandbox.read_file()
```

## Sandbox API

```python
sb = Sandbox("/path/to/workspace")

# 属性
sb.workspace          # str
sb.terminal           # PersistentTerminal (lazy)

# Shell
await sb.run_shell("ls -la", timeout_ms=30000)     # → str
async for chunk in sb.stream_shell("ls -la"): ...   # streaming

# 文件
await sb.read_file("src/main.py")                   # → str
await sb.write_file("out.txt", "content")           # → str
await sb.edit_file("cfg.json", [{"old":"a","new":"b"}])  # → str

# 生命周期
await sb.shutdown()
```

## 验证

```bash
# SSE
curl -X POST localhost:8000/api/agent/stream \
  -d '{"question":"say hi","max_steps":3}'
# → {"type":"finish","answer":"hi"}

# CLI
cd backend && uv run python cli.py
```
