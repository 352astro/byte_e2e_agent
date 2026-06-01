#!/usr/bin/env bash
# 在服务器上启动/重启后端（由 upload-backend.ps1 调用，也可手动执行）
set -euo pipefail

BACKEND_DIR="${1:-/opt/e2e_agent/backend}"
PORT="${2:-8000}"
LOG_DIR="$(dirname "$BACKEND_DIR")/logs"
PID_FILE="$(dirname "$BACKEND_DIR")/backend.pid"
LOG_FILE="${LOG_DIR}/backend.log"

mkdir -p "$LOG_DIR"
cd "$BACKEND_DIR"

if [[ ! -f .env ]]; then
  echo "错误: 未找到 ${BACKEND_DIR}/.env" >&2
  echo "请先在服务器创建: cp .env.example .env && 编辑 LLM_API_KEY、AGENT_WORKSPACE 等" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "错误: 未安装 uv。请执行:" >&2
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

echo "==> 安装/更新依赖 (uv sync)..."
uv sync

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "==> 停止旧进程 PID=$OLD_PID"
    kill "$OLD_PID" 2>/dev/null || true
    sleep 2
    kill -9 "$OLD_PID" 2>/dev/null || true
  fi
fi

# 兜底：清理遗留 uvicorn
pkill -f "uvicorn main:app.*--port ${PORT}" 2>/dev/null || true
sleep 1

echo "==> 启动 uvicorn (0.0.0.0:${PORT})..."
nohup uv run uvicorn main:app --host 0.0.0.0 --port "$PORT" >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"

sleep 2
if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "==> 后端已启动 PID=$(cat "$PID_FILE")"
  echo "    日志: $LOG_FILE"
  echo "    健康检查: curl -s http://127.0.0.1:${PORT}/api/hello"
else
  echo "错误: 进程启动失败，查看日志: $LOG_FILE" >&2
  tail -n 40 "$LOG_FILE" 2>/dev/null || true
  exit 1
fi
