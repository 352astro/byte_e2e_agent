# 后端全链路架构（v2）

## 分层概览

```
前端 (React + TypeScript)
  ↕ SSE + REST
FastAPI (app/)
  ↕
Project 服务 (app/services/project.py)  ← 组装一切
  ↕
AgentRuntime (agent/runtime.py)         ← ReAct 主循环
  ↕
actions (agent/actions.py)              ← model_call / execute_one_tool
  ↕                    ↕
LangChain LLM         HookManager (shared/hooks.py)
(agent/llm_lc.py)     ├─ StreamDriverHook → SSE 广播
                      ├─ MetricsHook     → SQLite 指标
                      └─ LoggingHook     → 控制台输出
  ↕
Message (shared/types.py) ← 前后端唯一定义，Pydantic，双向透传
  ↕
Workspace (agent/core/workspace.py) ← 路径管理 + I/O 代理
  ├─ run_shell()    临时子进程
  ├─ read_file()    Path 封装
  ├─ write_file()   Path 封装
  └─ resolve()      路径越界防护
```

## 核心类型 (`shared/types.py`)

前后端唯一真相源。Pydantic 定义，前端通过 JSON Schema 同步。

```
Message          — 消息容器（role/content/reasoning/tool_calls）
StreamEvent      — SSE 旁路传输协议（field 直接是 Message 属性名）
ToolCall         — OpenAI 工具调用格式
Turn             — 一次用户交互的元数据
```

**SSE 透传协议：`msg[ev.field] += ev.delta`** — 字段名即协议，前端直接镜像构建。

## Hook 系统 (`shared/hooks.py`)

- `BaseHook` — 12 个生命周期方法，每方法默认 no-op
- `HookManager` — 并行分发，单 hook 异常不影响其他 hook
- `StreamDriverHook` — 持有 `asyncio.Queue` 列表，广播 `StreamEvent`
- `MetricsHook` — 在 `on_message_finish` 时写 SQLite
- `LoggingHook` — 彩色控制台输出

## AgentRuntime (`agent/runtime.py`)

```
invoke_user(session, question)
  └─ _execute_turn(entry, question, max_steps, shadow_repo)
       ├─ hooks.on_turn_start()
       ├─ for step in range(max_steps):
       │    ├─ Message.assistant_message()
       │    ├─ hooks.on_message_start(msg)
       │    ├─ msg, finish_reason = model_call(llm, messages, tools, transcript_id, hooks)
       │    ├─ hooks.on_message_finish(msg, finish_reason, usage)
       │    │
       │    └─ for tc in msg.tool_calls:
       │         ├─ hooks.on_chunk_complete(msg, field="tool_calls", ...)
       │         ├─ tool_output = execute_one_tool(tc_dict, workspace, toolset, hooks)
       │         ├─ tool_result_msg = Message.tool_message(...)
       │         ├─ hooks.on_message_start(tool_result_msg)
       │         ├─ hooks.on_message_finish(tool_result_msg)
       │         └─ session.add_message(tool_result_msg)
       │
       └─ hooks.on_turn_end(turn_id, input_tokens, output_tokens)
```

## 流式 LLM 调用 (`agent/actions.py`)

```
model_call(llm, session_id, messages, tools, transcript_id, *, turn_id, interrupt_event, hooks)
  └─ msg = Message.assistant_message(transcript_id, turn_id)
       hooks.on_message_start(msg)
       for chunk in llm.astream(messages):
         if reasoning:  msg.reasoning += text;  hooks.on_chunk_delta(msg, "reasoning", text)
         if content:    msg.content += text;    hooks.on_chunk_delta(msg, "content", text)
         if tool_call:  msg.tool_calls[idx].function.name += name; hooks.on_chunk_delta(msg, "tool_calls", ...)
       msg.mark_complete()
       hooks.on_message_finish(msg, finish_reason, usage)
       return msg, finish_reason
```

## 工具执行 (`agent/actions.py`)

```
execute_one_tool(tc_dict, workspace, toolset, *, interrupt_event, llm_client, session_id, hooks) → str
  ├─ SubAgent → run_subagent(workspace, toolset, prompt, max_steps, hooks)  ← 独立 ReAct
  ├─ BrowserInspect → run_subagent(workspace, browser_toolset, prompt, hooks)
  └─ 其他 → tool.coroutine(**args, ws=workspace, session_id=session_id)  ← 直接调用 handler
```

## 工具定义 (`agent/tools/`)

每个工具 = **async 函数 + LangChain `StructuredTool.from_function()`**。

```
tools/
  registry.py    ToolRegistry 注册表 + OpenAI schema 生成
  toolset.py     ToolSet（按名称构建子集）
  __init__.py    全局 tool_registry，import 时自注册（17 个工具）
  shell.py       shell(command, timeout_ms) → ws.run_shell()
  read.py        read(path) → ws.read_file()
  write.py       write(path, content) → ws.write_file()
  edit.py        edit(path, edits) → ws.edit_file()
  grep.py        grep(regex, include, max_results) → re.compile() + Path.rglob()
  glob.py        glob(pattern, max_results) → Path.glob()
  search.py      web_search(query), web_fetch(url)
  subagent.py    subagent(prompt, max_steps) → execute_one_tool 分发
  browser.py     browser_open(url), browser_act(...), browser_inspect(prompt)
  task.py        task_list(), task_rewrite(tasks), task_update(id, status, summary)
  skill.py       load_skill(name)
  pyrepl.py      pyrepl(code)
```

## Session 存储 (`agent/session/_data.py`)

```
Session
  ├─ _messages: list[Message]           ← 内存真相源（Pydantic）
  ├─ _llm_context: list[dict]           ← OpenAI 格式缓存
  ├─ add_message(msg)                   ← 追加 + 同步落盘 JSONL
  ├─ get_messages() → list[dict]        ← API 序列化
  ├─ get_llm_context() → list[dict]     ← 发给 LLM
  └─ 持久化：Message.model_dump(mode='json') → JSONL

加载：_record_to_message(record)
  ├─ 新格式 {"id", "role", ...}     → Message.model_validate()
  ├─ 旧格式 {"uuid", "kind", "message"} → 转换
  └─ 更旧 {"role", "content"}         → 转换
```

## Workspace (`agent/core/workspace.py`)

纯 I/O 代理。无状态，不持终端，不做安全检查（交给 GuardHook）。

```
Workspace(root)
  ├─ 路径管理：agent_dir / sessions_dir / session_dir / messages_path
  ├─ 路径安全：resolve(relpath) → 防越界
  ├─ Shell：   run_shell(cmd, timeout_ms) → asyncio.create_subprocess_shell（临时子进程）
  ├─ 文件：    read_file(path) / write_file(path, content) / edit_file(path, edits)
  └─ Session 配置：save_session_config / load_session_config / list_session_ids
```

## 配置 (`agent/core/config.py`)

```
SessionConfig   — 不可变（frozen dataclass），创建时确定 tool_set / access / skills
AgentConfig     — 单次 LLM 调用参数（model_id, temperature, max_tokens）
AccessPolicy    — 访问控制（owner, visibility, invoke_permission, lifecycle）
```

## API 路由 (`app/api/routes/`)

```
/api/session/{sid}/chat     POST  → chat.py   启动 + SSE 流（StreamDriverHook）
/api/session/{sid}/stream   GET   → chat.py   重连（回放 + 直播）
/api/session/{sid}/respond  POST  → chat.py   权限响应
/api/session                POST  → sessions.py 创建
/api/sessions               GET   → sessions.py 列表
/api/session/{sid}          DELETE → sessions.py 删除
/api/session/{sid}/history  GET   → sessions.py 历史
/api/session/{sid}/commits  GET   → sessions.py Git 快照
/api/session/{sid}/checkout POST  → sessions.py 回退
/api/session/{sid}/interrupt POST  → sessions.py 中断
/api/metrics/llm/*          GET   → metrics.py  LLM 调用统计
```

## SSE 事件流

```
message_start       → 新 Message 开始
chunk_delta         → msg[field] += delta（前端直接 +=）
chunk_complete      → 结构化字段一次性完成
message_finish      → Message 完成
turn_complete       → Turn 结束，含 token 统计
interrupted         → 中断通知
```

## 文件分级

| 层级 | 目录 | 职责 |
|------|------|------|
| 共享类型 | `shared/` | Pydantic 类型定义 + Hook 基础设施 |
| 编排层 | `agent/` | ReAct 循环、工具执行、Session 管理 |
| 应用层 | `app/` | FastAPI 路由、Project 服务、配置 |
