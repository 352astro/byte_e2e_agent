#!/usr/bin/env bash
#
# 一键启动前后端开发服务器。
# 可在任意目录执行，脚本自动定位项目根目录。
#
# 用法:
#   ./start.sh              # 默认端口 8000 / 5173
#   PORT=9000 ./start.sh    # 自定义后端端口

set -euo pipefail

# ── 定位项目根目录 ──────────────────────────────────
ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── 默认工作目录：当前 agent 项目根目录 ───────────────────
DEFAULT_WORKSPACE="${AGENT_WORKSPACE:-$ROOT}"

# ── 端口配置 ────────────────────────────────────────
BACKEND_PORT="${PORT:-8000}"
FRONTEND_PORT=5173

# ── 清理函数 ────────────────────────────────────────
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    echo "Done."
}
trap cleanup EXIT INT TERM

# ── 启动后端 ────────────────────────────────────────
echo "=== Starting backend (port $BACKEND_PORT) ==="
cd "$ROOT/backend"
AGENT_WORKSPACE="$DEFAULT_WORKSPACE" uv run uvicorn main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload &
BACKEND_PID=$!

# ── 启动前端 ────────────────────────────────────────
echo "=== Starting frontend (port $FRONTEND_PORT) ==="
cd "$ROOT/frontend"
npm run dev -- --port "$FRONTEND_PORT" &
FRONTEND_PID=$!

# ── 等待就绪 ────────────────────────────────────────
sleep 2
echo ""
echo "=============================================="
echo "  Backend : http://localhost:$BACKEND_PORT"
echo "  Swagger : http://localhost:$BACKEND_PORT/docs"
echo "  Frontend: http://localhost:$FRONTEND_PORT"
echo "=============================================="
echo "Press Ctrl+C to stop both servers."
echo ""

wait
