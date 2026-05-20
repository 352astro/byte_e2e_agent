# Byte E2E Agent

FastAPI 后端 + React (Vite) 前端的 Hello World 项目骨架。

## 项目结构

```
byte_e2e_agent/
├── backend/                  # FastAPI 后端（Python 3.14+）
│   ├── main.py               # 入口，定义 / 和 /api/hello
│   └── pyproject.toml        # 依赖声明（uv / pip 通用）
├── frontend/                 # React 前端（Vite）
│   ├── src/App.jsx           # 页面组件
│   └── vite.config.js        # 含开发代理配置
└── .gitignore
```

## 环境要求

| 工具 | 最低版本 | 检查命令 |
|------|----------|----------|
| Python | 3.14 | `python --version` |
| Node.js | 20 | `node --version` |
| npm | 10 | `npm --version` |

## 快速开始

### 1. 后端

#### 方式 A：使用 uv（推荐）

```bash
cd backend
uv sync                        # 自动创建 venv 并安装依赖
uv run uvicorn main:app --reload --port 8000
```

#### 方式 B：使用 venv + pip

```bash
cd backend
python3.14 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install fastapi "uvicorn[standard]"
uvicorn main:app --reload --port 8000
```

启动后访问 `http://localhost:8000/docs` 查看 Swagger 文档。

### 2. 前端

```bash
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173`，页面会展示前端问候语并自动调用后端接口。

## 开发代理说明

开发模式下，前端 Vite 服务器监听 `5173` 端口，并将所有 `/api/*` 请求代理到后端 `localhost:8000`。因此前端代码中可以直接写 `fetch("/api/hello")`，无需关注跨域或绝对路径。

后端同样配置了 CORS 中间件，允许来自 `localhost:5173` 的请求。如果你使用不同的端口，需要修改 `backend/main.py` 中的 `allow_origins`。

## 常用命令

```bash
# 后端 — 生产运行
cd backend && uvicorn main:app --host 0.0.0.0 --port 8000

# 前端 — 生产构建
cd frontend && npm run build    # 产物在 frontend/dist/
npm run preview                 # 本地预览构建结果

# 前端 — 代码检查
cd frontend && npm run lint
```
