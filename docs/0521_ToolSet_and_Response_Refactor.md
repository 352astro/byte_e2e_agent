# 2026-05-21 — ToolSet 动态工具集 & 去除 Response 包装层

## 动机

1. **Response 包装层冗余**：DeepSeek 思考模式已通过 `reasoning_content` 提供真正的思考链，
   `thought` 字段沦为形式化的摘要，增加了解析复杂度和 token 消耗。
2. **硬编码 Union 笨重**：`Tool` / `SubTool` 联合类型在 `__init__.py` 中硬编码，
   每新增一个工具就要改 6 处引用，且无法运行时动态配置。

## 变更

### 新增

| 文件 | 说明 |
|------|------|
| `agent/tools/toolset.py` | `ToolSet` 类 — 动态生成 Pydantic 鉴别联合 |
| `agent/_json.py` | 新增 `safe_validate_json()` — 兼容 `TypeAdapter` 的三层自愈 |

### 删除

| 删除项 | 说明 |
|--------|------|
| `Response` 类 | 原 `{thought, action}` 包装层 |
| `SubResponse` 类 | 子 agent 专用包装层 |
| `run()` / `run_stream()` 的 `response_cls` 参数 | 不再需要 |
| `run()` / `run_stream()` 的 `tool_classes` 参数 | 由 `ToolSet` 取代 |

### 核心变更

#### LLM 输出格式

```
旧: {"thought": "用户说了hello...", "action": {"kind": "Finish", "answer": "Hi"}}
新: {"kind": "Finish", "answer": "Hi"}
```

#### ReActAgent 初始化

```python
# 旧
agent = ReActAgent(llm_client=llm)

# 新（toolset 可选，默认含全部工具）
agent = ReActAgent(llm_client=llm, toolset=ToolSet([Finish, Shell, Read, ...]))
```

#### 子 agent

```python
# 旧
sub_agent.run(question=..., response_cls=SubResponse, tool_classes=get_sub_tool_classes())

# 新
sub_agent = ReActAgent(llm_client, toolset=self._toolset.without(SubTask))
sub_agent.run(question=...)
```

#### Validation

```python
# 旧: Pydantic model
response = Response.model_validate_json(raw)
action = response.action

# 新: TypeAdapter (with json-repair)
action = safe_validate_json(raw, self._toolset.adapter)
```

### ToolSet API

```python
ts = ToolSet([Finish, Shell, Read, Write])

ts.adapter          # TypeAdapter — validate_json() 入口
ts.json_schema      # dict — 注入 system prompt
ts.json_schema_str  # str  — 格式化 JSON Schema

ts.without(SubTask) # 返回新 ToolSet，排除指定工具
```

## 影响范围

| 文件 | 变更量 |
|------|--------|
| `react.py` | 重写 (~-40 行)，移除 Response 相关代码 |
| `tools/__init__.py` | +1 import（ToolSet），Tool/SubTool 保留向后兼容 |
| `tools/toolset.py` | **新增** 73 行 |
| `_json.py` | 重构为 `_safe_validate()` 内部函数，新增 `safe_validate_json()` |
| `main.py` | 无需改动（`ReActAgent(llm_client=llm)` 仍有效） |
| `cli.py` | 无需改动 |
| 前端 | 无需改动（事件类型不变） |

## 验证

```bash
# ToolSet 功能
uv run python -c "
from agent.tools.toolset import ToolSet
from agent.tools import get_all_tool_classes
ts = ToolSet(get_all_tool_classes())
print(ts.adapter.validate_json('{\"kind\":\"Finish\",\"answer\":\"ok\"}').answer)
"

# SSE 端到端
curl -X POST localhost:8000/api/agent/stream \
  -d '{"question":"say hi","max_steps":3}'
# → {"type":"finish","answer":"Hi"}
```
