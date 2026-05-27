# 2026-05-22 — 原生 Tool Calls 迁移

## 动机

旧方案通过 system prompt 注入 JSON Schema，让 LLM 输出自定义 JSON
再由 Pydantic TypeAdapter 解析分发。这带来三个问题：

1. **JSON 解析不可靠** — 需要 json-repair 三层自愈
2. **非标准协议** — 无法利用 DeepSeek 思考模式与 tool_calls 的原生集成
3. **冗余字段** — 每个工具携带 `kind` 仅用于 Pydantic 联合类型分发

切换到 DeepSeek 原生 `tools` 参数后，函数名本身即为分发键，
`finish_reason` 完全替代 Finish 工具。

## 变更

### 核心

| 旧 | 新 |
|------|-----|
| system prompt 含完整 JSON Schema | system prompt 仅自然语言指令 |
| LLM 输出 JSON → TypeAdapter 解析 | 原生 `tool_calls` → 函数名分发 |
| `kind: Literal["Shell"]` | 类名即函数名，`kind` 字段移除 |
| `json-repair` 三层自愈 | 不再需要 |
| `safe_validate_json` | 不再需要 |
| `Finish` 工具判断结束 | `finish_reason == "stop"` |
| `_turns` 使用 `user` 角色存工具结果 | `_turns` 使用 `tool` 角色 + `tool_call_id` |

### 文件变更

| 文件 | 变更 |
|------|------|
| `agent/tools/toolset.py` | 重写 — `openai_tools` 属性 + `parse()` 方法 |
| `agent/tools/base.py` | 移除 `kind` 检查；新增 `function_name()` |
| `agent/tools/*.py` (9 个) | 移除 `kind` 字段 |
| `agent/llm.py` | `think_stream` 接受 `tools` 参数；yield `tool_call_chunk`/`finish_reason` |
| `agent/react.py` | 原生 tool_calls 引擎；移除 Finish 分发；Shell 流式内联 |
| `agent/tools/__init__.py` | 移除 `Finish`、`Tool`/`SubTool` 联合类型 |

### 退役

| 文件 | 原因 |
|------|------|
| `agent/tools/finish.py` | `finish_reason == "stop"` 完全替代 |
| `agent/utils/_json.py` | json-repair / safe_validate_json 无调用方 |
| `agent/tools/workspace.py` | 全局单例被 Sandbox 取代 |
| `explore_tool_calls.py` | 临时探索脚本 |
| `explore_pydantic_tool_schema.py` | 临时探索脚本 |

### 退役依赖

| 包 | 原因 |
|------|------|
| `json-repair` | 仅被已删除的 `_json.py` 引用 |

## 当前工具清单（9 个）

`Search`, `Shell`, `Read`, `Write`, `Edit`, `PlanRewrite`, `PlanAdvance`, `LoadSkill`, `SubTask`

## ToolSet API

```python
ts = ToolSet([Shell, Read, Write, ...])

ts.openai_tools           # → [{"type":"function","function":{...}}, ...]
ts.parse("Shell", args)   # → Shell(command="ls", timeout_ms=30000)
ts.without(SubTask)       # → 新 ToolSet
```

## LLM 交互流程

```
1. POST /chat/completions  (messages + tools)
2. 流式响应:
   reasoning_content    →  reasoning_token 事件
   tool_calls chunks    →  累积到 tool_calls_raw（同步推送 tool_call_stream）
   finish_reason        →  "tool_calls" 或 "stop"
3. 分发:
   finish_reason="stop"     →  content 为最终答案，对话结束
   finish_reason="tool_calls" →  解析 tool_calls → 执行 → 回传 tool 消息 → 继续循环
```

## 验证

```bash
curl -X POST localhost:8000/api/agent/stream \
  -d '{"question":"say hi","max_steps":3}'
# → {"type":"finish","answer":"Hi"}
```
