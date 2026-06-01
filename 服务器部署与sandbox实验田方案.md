# 服务器部署方案（精简版）

> 吃完饭回来按 **P0 清单** 逐项做即可。

---

## 一句话

```text
前端传 dist │ 后端传源码 │ 服务器配 env │ sandbox_repo 公有 git clone
```

不用 Docker。主项目私有仓**不必**在服务器配 GitHub。

---

## 架构

```text
PM 浏览器
   ↓ nginx
   ├─ /        → frontend/dist（本机构建后上传）
   └─ /api     → uvicorn :8000（backend 源码 + 服务器装依赖）

Agent 固定读写 → AGENT_WORKSPACE = sandbox_repo（服务器 git clone）
sandbox 演示服务 → 另开终端手动启动（暂不做 backend 托管）
```

---

## 服务器目录

```text
/opt/demo/
├── byte_e2e_agent/
│   ├── backend/              # 源码上传（tar/rsync）
│   ├── frontend/dist/        # 本机 build 后只上传 dist
│   └── deploy/               # 【待做】一键脚本 + nginx 示例
│
└── sandbox_repo/             # 公有仓 git clone
    └── .tmp/                 # session / metrics（自动生成）
```

---

## 上传什么（本机 → 服务器）

| 部分 | 上传内容 | 不要上传 |
|------|----------|----------|
| **前端** | `frontend/dist/` | `node_modules/`、源码 |
| **后端** | 整个 `backend/` 源码 | `.env`、`.venv/`、`__pycache__/` |
| **sandbox** | 不打包，服务器 `git clone` | — |

本机打包示例：

```bash
cd frontend && npm run build && cd ..
tar czvf deploy.tar.gz \
  --exclude='backend/.venv' --exclude='backend/.env' --exclude='**/__pycache__' \
  backend/ frontend/dist/
scp deploy.tar.gz user@server:/opt/demo/byte_e2e_agent/
```

---

## 服务器环境

| 工具 | 用途 |
|------|------|
| Python 3.14 + uv | 后端 |
| nginx | 静态前端 + 反代 `/api` |
| git | clone 公有 sandbox_repo |

**不需要**：Docker、服务器 GitHub 账号（主项目不上 git clone）。

---

## 服务器 `.env`（在服务器创建，勿从本机拷）

```text
LLM_API_KEY=...
LLM_BASE_URL=...
LLM_MODEL_ID=...
AGENT_WORKSPACE=/opt/demo/sandbox_repo    # 建议绝对路径
```

---

## 服务器上手命令（首次）

```bash
# 1. sandbox（公有仓）
git clone https://github.com/xxx/sandbox_repo.git /opt/demo/sandbox_repo

# 2. 解压主项目
mkdir -p /opt/demo/byte_e2e_agent && cd /opt/demo/byte_e2e_agent
tar xzvf deploy.tar.gz

# 3. 后端
cd backend
cp .env.example .env   # 编辑填入 LLM + AGENT_WORKSPACE
uv sync
uv run uvicorn main:app --host 0.0.0.0 --port 8000

# 4. nginx 指向 frontend/dist，/api 反代 localhost:8000

# 5. sandbox 演示服务（另开终端，按 sandbox README）
cd /opt/demo/sandbox_repo && ./scripts/start.sh   # 或 npm start
```

---

## 已有能力（不用改也能 demo）

- 单任务互斥：`/chat` 409 + 前端「系统正在繁忙」
- Agent 在 workspace 内 Shell/Read/Write/Grep
- Session 持久化、shadow 回滚

---

## 今晚 / 回来要做的事（P0）

- [ ] 本机 `npm run build`，打包 `backend/` + `frontend/dist/`
- [ ] 服务器装 Python / uv / nginx
- [ ] `git clone` 公有 sandbox_repo
- [ ] 服务器写 `backend/.env`
- [ ] `uv sync` + 启动 uvicorn
- [ ] 配 nginx
- [ ] 验证：打开页面 → 建 session → chat SSE → 第二人 409 繁忙

**待落地仓库内：**

- [ ] 新增 `deploy/start-prod.sh` + `deploy/nginx.conf.example` + `deploy/README.md`
- [ ] 生产 CORS 改域名（`app/core/config.py`）
- [ ] 可选：生产禁用 `POST /api/workspace/set`

---

## 明确不做（下一阶段）

| 事项 | 说明 |
|------|------|
| Docker | demo 不需要 |
| backend 托管 sandbox 进程 | 独立终端跑 repo 服务，稍后再做 backend 脚手架 |
| 持续 tail log / DeployService | 不内嵌 agent，以后 backend 层做 |
| Agent Skill 验证流程 | P1，部署跑通后再加 |

---

## 验收

1. 公网能打开前端，PM 能对话
2. Agent 能在 sandbox_repo 改代码
3. 第二人同时 chat 看到「系统正在繁忙」
4. sandbox 服务手动启动后可访问（验证改代码效果）

---

## 文件速查

| 用途 | 路径 |
|------|------|
| env 模板 | `backend/.env.example` |
| workspace | `backend/app/core/config.py` |
| 409 / 聊天 | `backend/app/services/chat_service.py` |
| 开发启动 | `start.sh` |
| 生产部署 | `deploy/`（待新增） |
