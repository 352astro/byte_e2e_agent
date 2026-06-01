#!/usr/bin/env bash
#
# 构建前端并上传到服务器（SSH 密码在终端手动输入）
#
# 用法（在项目根目录或任意目录执行均可）:
#   ./deploy/upload-frontend.sh
#   SSH_USER=ubuntu ./deploy/upload-frontend.sh
#
# 依赖: bash, npm, ssh, rsync（Git Bash / WSL / macOS / Linux）
# Windows 请用: .\deploy\upload-frontend.ps1
#
set -euo pipefail

# ── 可覆盖的环境变量 ─────────────────────────────────
SERVER="${SERVER:-124.223.29.15}"
SSH_USER="${SSH_USER:-root}"
REMOTE_DIR="${REMOTE_DIR:-/root/e2e_agent/frontend}"
# 可选: SSH_KEY=~/.ssh/id_rsa  →  免密则不会提示密码
SSH_KEY="${SSH_KEY:-}"

# ── 定位项目根目录 ───────────────────────────────────
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="$ROOT/frontend"
DIST="$FRONTEND/dist"

SSH_OPTS=()
if [[ -n "$SSH_KEY" ]]; then
  SSH_OPTS=(-i "$SSH_KEY")
fi

REMOTE="${SSH_USER}@${SERVER}"

echo "==> 项目根目录: $ROOT"
echo "==> 目标服务器: ${REMOTE}:${REMOTE_DIR}"
echo ""

# ── 1. 构建前端 ─────────────────────────────────────
echo "==> [1/2] 构建前端 (npm run build)..."
cd "$FRONTEND"
if [[ ! -d node_modules ]]; then
  echo "    node_modules 不存在，执行 npm install..."
  npm install
fi
npm run build

if [[ ! -d "$DIST" ]]; then
  echo "错误: 构建产物不存在: $DIST" >&2
  exit 1
fi
echo "    构建完成: $DIST"
echo ""

# ── 2. 上传 dist（单次 SSH，只需输入一次密码）────────
echo "==> [2/2] 上传 dist/ → ${REMOTE_DIR}/（将提示输入 SSH 密码）..."
tar czf - -C "$DIST" . | ssh "${SSH_OPTS[@]}" "$REMOTE" \
  "rm -rf '${REMOTE_DIR}' && mkdir -p '${REMOTE_DIR}' && tar xzf - -C '${REMOTE_DIR}'"

echo ""
echo "=============================================="
echo "  前端部署完成"
echo "  远程路径: ${REMOTE}:${REMOTE_DIR}/"
echo "  请确认 nginx 的 root 指向该目录，且 /api 反代后端"
echo "=============================================="
