# 2026-05-23 — 可复用交互式暂停接口 (async generator + Future)

## 动机

当前 SSE 流一旦开始，后端进入纯输出模式，无法等待用户输入。
如果未来需要实现以下交互，现有架构不支持：

- 工具执行前需用户授权（permission gate）
- 危险操作二次确认
- LLM 执行过程中向用户澄清意图
- 请求用户提供额外参数

需要一个**通用机制**让 SSE 流在某一点暂停、等待用户 HTTP 响应后自动恢复，
且不新建连接、不改 WebSocket、不破坏现有 `run_stream` 主循环。

## 工作原理

```
前端 POST /chat → SSE 流建立

  run_stream async generator
    └─ async for event in _execute_one_tool(...)
         └─ _execute_one_tool:
              yield {"type": "request_user_input", "request_id": "abc", ...}
              response = await future            ← ❶ 挂起 (协程栈帧保留)

  ... event loop 空闲，处理其他 HTTP 请求 ...

  用户点击"批准" → POST /api/session/{sid}/respond
    → resolve_request("abc", {"approved": true})
      → future.set_result({"approved": true})   ← ❷ 唤醒

              response = {"approved": true}      ← ❸ 从这里继续
              # 检查 response，决定是否执行工具
```

核心原理：

- `asyncio.Future` — 充当一次性的跨协程通道；`await` 方阻塞，`set_result` 方唤醒
- async generator — `yield` 后 `await` 时，Python 保留整个栈帧（局部变量 `func_name`、`tool_params`、`action` 等不丢失），event loop 可在此期间处理其他连接
- SSE — 连接保持 open，不产新事件，前端渲染等待 UI

## 新增接口

### ReActAgent（3 个成员）

```python
_pending: dict[str, asyncio.Future]   # request_id → Future

async def _request_user_input(
    self, request_type: str, payload: dict
) -> dict:
    """Yield 等待事件 → await Future → return 用户响应"""
    request_id = uuid.uuid4().hex
    future: asyncio.Future[dict] = asyncio.Future()
    self._pending[request_id] = future

    yield {
        "type": "request_user_input",
        "request_id": request_id,
        "request_type": request_type,
        "payload": payload,
    }
    return await future

def resolve_request(self, request_id: str, response: dict) -> None:
    """由 API 端点调用，唤醒对应的 Future"""
    future = self._pending.pop(request_id, None)
    if future is not None:
        future.set_result(response)
```

### API 端点（1 个）

```
POST /api/session/{sid}/respond
Body: { "request_id": "abc", "response": {...} }
  → sessions.get(sid).resolve_request(rid, response)
  → 200 { "ok": true }
```

### SSE 事件（1 个）

```json
{
  "type": "request_user_input",
  "request_id": "abc",
  "request_type": "permission",
  "payload": { "tool": "Shell", "command": "rm -rf ..." }
}
```

### 前端（2 处改动）

```
useAgentStream.ts:  dispatch 新增 request_user_input 分支 → 写入 step.events
ToolRenderers.tsx:  renderToolEvent 新增渲染函数 → 按 request_type 展示对应 UI
                   用户操作后 POST /api/session/{sid}/respond
```

## 可复用性

`request_type` 决定两件事：

| request_type | 后端解释 | 前端 UI |
|-------------|---------|---------|
| `"permission"` | `response` 含 `approved: bool`，不通过则跳过执行 | 权限弹窗 |
| `"confirm"` | `response` 含 `confirmed: bool` | 确认框 |
| `"clarify"` | `response` 含 `answer: str`，作为 LLM 补充上下文 | 输入框 |
| `"input"` | `response` 含 `value: str/number/...`，作为工具参数 | 表单 |

追加新 `request_type` 只需在前端 `ToolRenderers` 和新工具代码中各加一个分支，无需改动基础设施。

## 工具集成示例（Permission gate）

```python
# 工具执行前
if func_name == "Shell" and _is_dangerous(action.command):
    async for event in self._request_user_input(
        "permission",
        {"tool": func_name, "command": action.command},
    ):
        yield event  # 将等待事件传递到 SSE 流
    # 生成器恢复后继续执行原工具
```

`_request_user_input` 是 async generator（含 `yield`），调用处需 `async for` 将事件传递到 SSE 流。调用方无需了解 `Future` 细节。

## 改动范围

| 文件 | 改动 | 行数 |
|------|------|------|
| `agent/react.py` | `_pending` dict + `_request_user_input()` + `resolve_request()` | +30 |
| `main.py` | `POST /api/session/{sid}/respond` 端点 | +10 |
| `src/types.ts` | `SSEEvent` / `ToolEvent` 新增 `request_user_input` 变体 | +5 |
| `src/hooks/useAgentStream.ts` | dispatch 新增分支 | +5 |
| `src/components/ToolRenderers.tsx` | 渲染函数 | +20 |

## 超时与错误

- Future 未 resolve → async generator 永久挂起
- 需在 `resolve_request` 外增加 `cancel_request`: `future.cancel()`，`await` 处抛 `CancelledError`
- `clear()` 时遍历 `_pending` 全部 cancel
- 前端可传入 `timeout_ms` 参数，超时自动 cancel

## 不涉及

- 不新建 WebSocket 连接
- 不改变现有工具执行流程
- 不修改 `run_stream` 主循环结构
