# Backend + Agent 解耦技术方案与任务清单

> 目标：降低后端 API 层、业务 service 层与 agent 运行时之间的耦合，让 `router` 只负责 HTTP 协议适配，让后端服务逻辑沉淀到 `app/services/`，让 `agent/` 成为可被 service 调用的基础能力层。

## 1. 当前架构分析

### 1.1 当前主链路

```text
Frontend
  -> FastAPI Router
  -> app/services/project.py: Project
  -> agent/scheduler.py: Scheduler
  -> agent/actions.py / agent/llm.py / agent/tools/*
  -> TranscriptStream
  -> SSE
```

当前分层已经具备雏形：

| 层级 | 位置 | 当前职责 |
|---|---|---|
| API 层 | `backend/app/api/routes/` | HTTP 路由、请求参数校验、SSE 输出 |
| Schema 层 | `backend/app/schemas/` | Pydantic 请求模型 |
| Service 层 | `backend/app/services/project.py` | workspace、session、scheduler、metrics、shadow repo 的统一门面 |
| Agent 层 | `backend/agent/` | ReAct 循环、LLM 调用、工具执行、transcript、sandbox、shadow repo |
| Core 层 | `backend/app/core/` | 配置、CORS、全局常量 |

### 1.2 主要耦合问题

1. `router` 仍包含服务逻辑。
   - `sessions.py` 直接调用 `project.shadow_repo`、`project.scheduler`。
   - `sessions.py` 直接访问 `session._transcripts`、`session._sandbox`。
   - `sessions.py` 直接 import `agent.tools.task.reconstruct_tasks`。
   - `chat.py` 的 `/respond` 直接使用 `project.scheduler.resolve(...)`。

2. `Project` service 过大。
   - 当前 `Project` 同时负责 workspace、session 生命周期、chat 启动、stream 获取、metrics、shadow repo、scheduler 创建。
   - 这适合作为早期 facade，但后续会变成上帝对象，不利于测试和多人协作。

3. `agent` 反向依赖 `app`。
   - `agent/session.py`、`agent/scheduler.py`、`agent/shadow_repo.py`、`agent/tools/grep.py`、`agent/tools/glob.py`、`agent/tools/task.py` 依赖 `app.core.config.TMP_DIR`。
   - 这会让 agent 无法作为独立基础服务或独立包复用。

4. Agent 内部状态泄漏到后端。
   - 后端路由知道 `Session` 私有字段和 `Scheduler` 内部运行模型。
   - 一旦 agent 同学调整 transcript、sandbox、scheduler 实现，API 层容易被动破坏。

5. 并发与状态边界不清晰。
   - 当前一个 `Project` 只有一个全局 `Scheduler`，一次只能运行一个 session。
   - `/session/{sid}/status` 当前读取全局 `scheduler.state`，A session 运行时查询 B session 也可能显示 running。

## 2. 改造目标

### 2.1 分层目标

改造后调用链应为：

```text
Frontend
  -> FastAPI Router
  -> app/services/*
  -> agent public API
  -> agent internal runtime
```

目标边界：

| 层级 | 改造后职责 | 禁止事项 |
|---|---|---|
| Router | 只做 HTTP 入参、出参、异常映射、SSE 包装 | 不直接访问 agent，不写业务流程，不访问私有字段 |
| Service | 编排业务用例，聚合 agent 基础能力，返回稳定 DTO | 不暴露 agent 内部对象给 router |
| Agent 基础服务 | 提供 session、scheduler、transcript、shadow repo、metrics 等函数或接口 | 不反向 import `app`，不理解 HTTP |
| Agent 内部实现 | ReAct 循环、tools、LLM、sandbox、持久化细节 | 不被 router 直接调用 |

### 2.2 代码组织目标

建议演进为：

```text
backend/
  app/
    api/
      routes/
        chat.py
        sessions.py
        workspace.py
        metrics.py
    schemas/
      chat.py
      sessions.py
      workspace.py
    services/
      project.py          # 组合根 / facade，逐步变薄
      chat_service.py     # chat、stream、respond
      session_service.py  # session 生命周期、history、recover、status
      checkpoint_service.py # shadow repo、checkout、commits
      metrics_service.py  # LLM metrics 查询
      workspace_service.py # workspace 获取和切换
  agent/
    config.py             # agent 自己的默认配置和常量
    public.py             # 可选：agent 对 app 暴露的稳定入口
    scheduler.py
    session.py
    shadow_repo.py
    transcript.py
    ...
```

## 3. 目标架构设计

### 3.1 Router 层

Router 只保留四类职责：

1. 声明 URL、HTTP method、请求模型。
2. 通过 FastAPI dependency 获取 service。
3. 调用 service。
4. 将领域异常转换为 `HTTPException`，或将 stream 包装成 SSE response。

示例目标形态：

```python
@router.post("/session/{sid}/checkout")
async def checkout_commit(
    sid: str,
    req: CheckoutRequest,
    session_service: SessionService = Depends(get_session_service),
):
    try:
        return await session_service.checkout_session(sid, req)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail="Session not found")
    except CommitNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
```

### 3.2 Service 层

Service 层按业务用例拆分，`Project` 只作为组合根保留一段时间。

建议 service：

| Service | 职责 | 主要方法 |
|---|---|---|
| `WorkspaceService` | workspace 查询、切换、路径解析 | `get_workspace()`、`set_workspace(path)`、`resolve_workspace(path)` |
| `SessionService` | session 创建、删除、加载、history、recover、status | `create_session()`、`list_sessions()`、`delete_session(sid)`、`get_history(sid)`、`get_recovery_state(sid)`、`get_session_status(sid)` |
| `ChatService` | 启动 agent、SSE stream 数据源、响应人机交互 | `start_chat(sid, question, max_steps)`、`get_stream(sid)`、`respond_to_pending(transcript_id, response)` |
| `CheckpointService` | shadow repo、commit 查询、checkout、restore、任务重建 | `list_commits(sid)`、`get_commit(sid, sha)`、`checkout_session(sid, payload)` |
| `MetricsService` | LLM metrics 查询 | `list_llm_calls(...)`、`get_llm_summary(...)`、`get_llm_dashboard(...)` |

短期可以先把方法补到 `Project`，再逐步拆分成独立 service，避免一次重构过大。

### 3.3 Agent 层

Agent 层应作为基础服务，提供稳定、最小的公开 API。

建议公开能力：

```python
class AgentRuntime:
    def load_session(self, workspace: str, session_id: str) -> AgentSessionHandle: ...
    def create_scheduler(self) -> AgentSchedulerHandle: ...
    def create_shadow_repo(self, workspace: str, repo_dir: str) -> AgentCheckpointStore: ...
```

或者先采用轻量函数式接口：

```python
from agent.session import load_session, get_history, clear
from agent.scheduler import Scheduler
from agent.shadow_repo import ShadowRepo
from agent.transcript import TranscriptStream
```

关键约束：

1. `agent/` 不 import `app/`。
2. `agent/` 不返回 HTTP 概念。
3. `agent/` 对外暴露公共方法，不要求上层访问 `_transcripts`、`_sandbox`。
4. `Session` 增加必要 public 方法，例如：
   - `find_user_question_content(transcript_id: str) -> str`
   - `reconstruct_tasks() -> None`
   - `truncate_by_transcript(transcript_id: str, keep: bool) -> int`
   - `get_sandbox()` 可暂时保留，但优先封装成更明确的方法。

## 4. 关键改造方案

### 4.1 收敛 router 到 service

优先处理以下路由：

| 文件 | 当前问题 | 目标 |
|---|---|---|
| `routes/sessions.py` | checkout 逻辑过重，直接操作 agent 内部对象 | 下沉到 `SessionService` / `CheckpointService` |
| `routes/sessions.py` | status 读取全局 scheduler state | 改为 `service.get_session_status(sid)` |
| `routes/sessions.py` | interrupt 直接调用 scheduler | 改为 `service.interrupt_session(sid)` / `service.interrupt_current()` |
| `routes/chat.py` | respond 直接调用 scheduler | 改为 `chat_service.respond_to_pending(...)` |
| `routes/metrics.py` | 可接受，但仍绑定 `Project` | 后续改为 `MetricsService` |
| `routes/workspace.py` | 可接受，但仍绑定 `Project` | 后续改为 `WorkspaceService` |

### 4.2 拆分 `Project`

第一阶段保留 `Project` facade，新增更明确的方法：

```python
class Project:
    def get_session_status(self, session_id: str) -> dict: ...
    def respond_to_pending(self, transcript_id: str, response: dict) -> None: ...
    async def interrupt_session(self, session_id: str) -> bool: ...
    async def interrupt_current(self) -> bool: ...
    def list_commits(self, session_id: str) -> dict: ...
    def get_commit(self, session_id: str, sha: str) -> dict: ...
    async def checkout_session(self, session_id: str, req: CheckoutRequest) -> dict: ...
```

第二阶段拆成独立 service：

```text
Project
  -> owns WorkspaceContext / AgentRuntime dependencies
  -> builds SessionService, ChatService, CheckpointService, MetricsService
```

第三阶段让 router 依赖具体 service，不再依赖 `Project`。

### 4.3 移除 agent 对 app 的反向依赖

新增：

```text
backend/agent/config.py
```

内容：

```python
DEFAULT_TMP_DIR = ".tmp"
```

替换以下文件中的 `from app.core.config import TMP_DIR`：

| 文件 | 替换方式 |
|---|---|
| `agent/session.py` | `from agent.config import DEFAULT_TMP_DIR as TMP_DIR` |
| `agent/scheduler.py` | `from agent.config import DEFAULT_TMP_DIR as TMP_DIR` |
| `agent/shadow_repo.py` | `from agent.config import DEFAULT_TMP_DIR as TMP_DIR` |
| `agent/tools/grep.py` | `from agent.config import DEFAULT_TMP_DIR as TMP_DIR` |
| `agent/tools/glob.py` | `from agent.config import DEFAULT_TMP_DIR as TMP_DIR` |
| `agent/tools/task.py` | `from agent.config import DEFAULT_TMP_DIR as TMP_DIR` |

后续如需动态配置，再把 `tmp_dir` 通过 `AgentRuntimeConfig` 注入，不要让 agent 依赖 `app`。

### 4.4 封装 checkout 流程

当前 checkout 包含：

1. 校验 session。
2. restore commit。
3. 从 transcript 中取用户问题。
4. truncate transcripts。
5. reconstruct tasks。
6. set shadow repo HEAD。
7. 返回 removed / user_content。

目标封装到 `CheckpointService.checkout_session(...)`：

```text
Router
  -> CheckpointService.checkout_session(sid, req)
    -> SessionRepository.get(sid)
    -> ShadowRepo.restore(...)
    -> AgentSession.truncate...
    -> AgentTaskService.reconstruct(...)
    -> ShadowRepo.set_head(...)
    -> CheckoutResult
```

同时将裸 dict 返回收敛为明确 schema：

```python
class CheckoutResult(BaseModel):
    ok: bool
    commit_sha: str | None
    removed: int
    user_content: str
```

### 4.5 修正 session status 语义

当前语义风险：

```python
return {"running": project.scheduler.state != "idle"}
```

目标：

```python
return project.get_session_status(sid)
```

service 内部：

```python
def get_session_status(self, session_id: str) -> dict:
    self.get_session(session_id)
    return {"running": self.scheduler.is_running_session(session_id)}
```

### 4.6 定义异常边界

新增 `app/services/errors.py`：

```python
class ServiceError(Exception): ...
class SessionNotFound(ServiceError): ...
class CommitNotFound(ServiceError): ...
class AgentBusy(ServiceError): ...
class PendingRequestNotFound(ServiceError): ...
class InvalidWorkspace(ServiceError): ...
```

Service 内部捕获底层 `KeyError` / `ValueError` / `RuntimeError`，转换成领域异常。

Router 只映射：

| Service 异常 | HTTP 状态码 |
|---|---|
| `SessionNotFound` | 404 |
| `CommitNotFound` | 404 |
| `PendingRequestNotFound` | 404 |
| `InvalidWorkspace` | 400 |
| `AgentBusy` | 409 |

## 5. 推荐迁移顺序

### Phase 0：锁定边界和测试基线

目标：先保证现有行为可回归。

任务：

- [x] 新增 `backend/tests/test_api_http.py`：subprocess 启动完整 uvicorn 实例，httpx 发真实 HTTP 请求，断言响应符合预期（不依赖 TestClient / ASGI 内存调用）。
- [x] 覆盖 health / workspace / session / chat / stream / respond / checkout / interrupt / metrics 全量 API 端点。
- [x] 补充关键行为断言：session 404 / 幂等 DELETE、checkout 空 body 与无效 commit、respond 无 pending 时 404、chat 409 冲突、metrics 查询参数、chat 后 history / recover / shadow commit / SSE 重连。
- [x] 在 `pyproject.toml` 增加 dev 依赖（`pytest`、`pytest-asyncio`、`httpx`），标记 `@pytest.mark.integration`。

验收标准：

- [x] `uv run pytest tests/test_api_http.py -v -m integration` 全部通过，作为后续改造的回归基线。
- [ ] 改造前后 API response 字段保持兼容（后续 Phase 改造时对照本测试套件验证）。

### Phase 1：让 router 变薄

目标：清除 `router` 中的业务逻辑和 agent 内部访问。

任务：

- [x] 在 `Project` 中新增 `respond_to_pending(transcript_id, response)`。
- [x] 在 `Project` 中新增 `get_session_status(session_id)`，修复全局 scheduler 状态误判。
- [x] 在 `Project` 中新增 `interrupt_session(session_id)` 和 `interrupt_current()`。
- [x] 在 `Project` 中新增 `list_commits(session_id)`、`get_commit(session_id, sha)`。
- [x] 在 `Project` 中新增 `checkout_session(session_id, req)`，迁移 `sessions.py` 中的 checkout 逻辑。
- [x] 修改 `chat.py` 和 `sessions.py`，禁止直接访问 `project.scheduler`、`project.shadow_repo`、`session._transcripts`、`session._sandbox`。
- [x] 将 `agent.tools.task.reconstruct_tasks` 的调用移出 router。

验收标准：

- [x] `backend/app/api/routes/*.py` 中不再出现 `agent.` import。
- [x] `backend/app/api/routes/*.py` 中不再出现 `._transcripts`、`._sandbox`、`.scheduler`、`.shadow_repo`。
- [x] `/api/session/{sid}/status` 只反映当前 sid 是否运行。

### Phase 2：拆分 service

目标：降低 `Project` 的复杂度。

任务：

- [ ] 新建 `app/services/session_service.py`。
- [ ] 新建 `app/services/chat_service.py`。
- [ ] 新建 `app/services/checkpoint_service.py`。
- [ ] 新建 `app/services/metrics_service.py`。
- [ ] 新建 `app/services/workspace_service.py`。
- [ ] 将 `Project` 改为组合根，负责创建和持有共享依赖。
- [ ] 在 `app/dependencies.py` 中增加 `get_session_service`、`get_chat_service`、`get_checkpoint_service`、`get_metrics_service`、`get_workspace_service`。
- [ ] Router 从依赖 `Project` 逐步改为依赖具体 service。

验收标准：

- [ ] `Project` 不再直接承载所有业务用例。
- [ ] 每个 route 文件只依赖自身需要的 service。
- [ ] 每个 service 可独立单测，不需要启动 FastAPI。

### Phase 3：agent 基础服务化

目标：让 `agent/` 成为后端 service 可调用的基础能力层。

任务：

- [ ] 新建 `agent/config.py`，迁移 `TMP_DIR` 常量。
- [ ] 移除 `agent/` 对 `app.core.config` 的 import。
- [ ] 为 `Session` 增加必要 public 方法，替代 `_transcripts` / `_sandbox` 外部访问。
- [ ] 可选新增 `agent/public.py` 或 `agent/runtime.py`，统一导出后端需要的 agent 能力。
- [ ] 明确 agent public API 文档，标注哪些是稳定接口，哪些是内部实现。

验收标准：

- [ ] `backend/agent/**/*.py` 中不再出现 `from app.` 或 `import app.`。
- [ ] 后端 service 不访问 agent 私有字段。
- [ ] agent 可以被纯 Python 单测直接实例化，不依赖 FastAPI app。

### Phase 4：并发与可部署性增强

目标：为公网 demo 或多人访问降低运行时风险。

任务：

- [ ] 明确当前单 scheduler 限制：同一 workspace 同一时间只允许一个 agent 运行。
- [ ] 在 service 层将 `RuntimeError("Scheduler already running")` 转换为 `AgentBusy`。
- [ ] 前端收到 409 时提示当前已有任务运行。
- [ ] 如需多人并发，设计 `SchedulerManager`：按 workspace 或 session 管理 scheduler。
- [ ] 检查 `.tmp/`、SQLite metrics、shadow repo 的可写目录和清理策略。

验收标准：

- [ ] 并发冲突时 API 返回明确 409。
- [ ] 不会出现多个 agent 同时写同一个 workspace 的未定义行为。

## 6. 文件级任务清单

### P0：必须完成

- [x] `backend/app/services/project.py`
  - [x] 新增 `get_session_status`。
  - [x] 新增 `respond_to_pending`。
  - [x] 新增 `interrupt_session`、`interrupt_current`。
  - [x] 新增 `list_commits`、`get_commit`。
  - [x] 新增 `checkout_session`。

- [x] `backend/app/api/routes/chat.py`
  - [x] `/respond` 改为调用 `project.respond_to_pending(...)`。
  - [x] 保留 SSE 协议包装逻辑。

- [x] `backend/app/api/routes/sessions.py`
  - [x] 删除 `from agent.tools.task import reconstruct_tasks`。
  - [x] 删除对 `project.scheduler` 的直接访问。
  - [x] 删除对 `project.shadow_repo` 的直接访问。
  - [x] 删除对 `session._transcripts`、`session._sandbox` 的直接访问。
  - [x] checkout、interrupt、status、commits 全部转发给 service。

### P1：建议完成

- [ ] `backend/agent/config.py`
  - [ ] 新增 agent 层常量。

- [ ] `backend/agent/session.py`
  - [ ] 替换 `app.core.config` 依赖。
  - [ ] 增加 transcript 查询和任务重建相关 public 方法。

- [ ] `backend/agent/scheduler.py`
  - [ ] 替换 `app.core.config` 依赖。
  - [ ] 评估是否把 snapshot 逻辑进一步下沉为可注入 checkpoint service。

- [ ] `backend/agent/shadow_repo.py`
  - [ ] 替换 `app.core.config` 依赖。
  - [ ] 保持其作为 agent 基础 checkpoint 能力。

- [ ] `backend/agent/tools/grep.py`
  - [ ] 替换 `app.core.config` 依赖。

- [ ] `backend/agent/tools/glob.py`
  - [ ] 替换 `app.core.config` 依赖。

- [ ] `backend/agent/tools/task.py`
  - [ ] 替换 `app.core.config` 依赖。
  - [ ] 为 task reconstruct 提供更明确的 public API。

### P2：架构优化

- [ ] `backend/app/services/session_service.py`
  - [ ] 从 `Project` 拆出 session 生命周期逻辑。

- [ ] `backend/app/services/chat_service.py`
  - [ ] 从 `Project` 拆出 chat、stream、respond 逻辑。

- [ ] `backend/app/services/checkpoint_service.py`
  - [ ] 从 `Project` 拆出 shadow repo 与 checkout 逻辑。

- [ ] `backend/app/services/metrics_service.py`
  - [ ] 从 `Project` 拆出 metrics 查询逻辑。

- [ ] `backend/app/services/workspace_service.py`
  - [ ] 从 `Project` 拆出 workspace 逻辑。

- [ ] `backend/app/dependencies.py`
  - [ ] 增加具体 service 的 dependency provider。

## 7. 回归测试清单

### 自动化测试

- [ ] 运行现有测试：

```bash
cd backend
uv run pytest
```

- [ ] 新增 service 单测：
  - [ ] `test_project_session_status.py`
  - [ ] `test_project_checkout.py`
  - [ ] `test_project_interrupt.py`
  - [ ] `test_project_respond.py`

### 手工验收链路

- [ ] `POST /api/session` 创建 session。
- [ ] `GET /api/sessions` 能看到新 session。
- [ ] `POST /api/session/{sid}/chat` 能返回 SSE。
- [ ] `GET /api/session/{sid}/stream` 刷新后能恢复 stream 或 flush 历史。
- [ ] `GET /api/session/{sid}/history` 返回历史。
- [ ] `GET /api/session/{sid}/recover` 返回 transcripts 和 running。
- [ ] `GET /api/session/{sid}/status` 只判断当前 sid 是否运行。
- [ ] `POST /api/session/{sid}/respond` 能响应 pending request。
- [ ] `GET /api/session/{sid}/commits` 能返回 shadow commits。
- [ ] `POST /api/session/{sid}/checkout` 能恢复 workspace、截断 transcript、重建 tasks。
- [ ] `POST /api/session/{sid}/interrupt` 能中断当前 session。
- [ ] `POST /api/interrupt` 能中断当前全局运行任务。
- [ ] `GET /api/metrics/llm/summary` 能返回 metrics。

## 8. 最终验收标准

架构验收：

- [ ] Router 不包含业务流程。
- [ ] Router 不 import `agent.*`。
- [ ] Router 不访问 agent 私有字段或 `Project` 内部组件。
- [ ] Service 是后端业务逻辑唯一入口。
- [ ] Agent 不 import `app.*`。
- [ ] Agent 对 service 暴露稳定 public API。

行为验收：

- [ ] 原有 API 对前端保持兼容。
- [ ] chat、stream、recover、history、checkout、interrupt、metrics 全链路可用。
- [ ] 单 scheduler 忙碌状态返回明确 409。
- [ ] session status 不再误报其他 session 的运行状态。

工程验收：

- [ ] 新增或更新单测覆盖核心 service。
- [ ] 现有测试全部通过。
- [ ] 文档更新：README 或架构文档说明新的层次边界。

## 9. 建议优先级总结

如果时间有限，按以下顺序执行：

1. 先把 `chat.py`、`sessions.py` 中直接访问 agent 内部的逻辑全部下沉到 `Project`。
2. 修复 `/session/{sid}/status` 的全局状态误判。
3. 移除 `agent/` 对 `app.core.config` 的反向依赖。
4. 再把 `Project` 拆成具体 service。
5. 最后处理多 scheduler / 多用户并发模型。

完成前三步后，后端与 agent 的边界会明显收紧，足以支撑后续继续服务化拆分和部署演示。
