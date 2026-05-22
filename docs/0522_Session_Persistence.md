# 2026-05-22 — Session 持久化（过渡方案）

## 动机

服务重启或崩溃后，所有会话数据（对话历史）丢失，用户需从头开始。
需要一个最简过渡方案：**结束时存盘，启动时恢复**，不侵入 agent 内部逻辑。

## 设计

持久化文件：`workspace/.tmp/sessions.json`

每个 session 保存四项可序列化数据：
- `system_msg` — 注入 system prompt 后的消息对象
- `question_msg` — 当前轮次的用户问题对象
- `turns` — LLM 对话上下文（`list[dict]`，OpenAI 消息格式）
- `turns_history` — 结构化 Turn 快照（`list[dict]`，供前端 history API）

恢复时按原样重建 `ReActAgent` 实例（新 `SandBox`，共享 `HelloAgentsLLM`）。

## 触发时机

| 时机 | 说明 |
|------|------|
| `SessionManager.__init__` | 调用 `_load()` 尝试恢复 |
| `POST /api/session/{sid}/chat` 流结束 | `finally: sessions.save()` |
| `SessionManager.delete()` | session 被删除后存盘 |
| FastAPI `shutdown` 事件 | 服务正常停止时存盘 |

## 变更

| 文件 | 说明 |
|------|------|
| `backend/session_manager.py` | 新增 `_save()` / `_load()` / `save()` 方法；`__init__` 调用 `_load()`；`delete()` 调用 `_save()` |
| `backend/main.py` | chat 端点 `finally` 中调用 `sessions.save()`；新增 `shutdown` 事件 |

## 未修改

- `backend/agent/` 目录 — 零改动
- 持久化仅存取 `_system_msg` / `_question_msg` / `_turns` / `_turns_history` 四个实例属性，不依赖任何内部方法

## 局限性（过渡方案固有）

- 仅在流正常结束（含客户端断开）和正常关机时存盘；`kill -9` / 崩溃无保护
- 恢复后的 session 使用全新 `SandBox`（终端 `cd` 状态丢失，但这是 agent 设计上的无状态预期）
- 无版本兼容：若 Turn 结构变更，旧持久化文件加载将失败（静默跳过）
- 无并发保护：多 worker 场景下同一文件可能被覆盖
- 旧 session 的文件系统副作用（SandBox 中创建的文件）不会随持久化恢复
