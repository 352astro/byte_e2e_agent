#!/usr/bin/env bash
#
# 一键启动 CLI 终端对话。
# 可在任意目录执行，脚本自动定位项目根目录，
# 并以调用时所在目录作为工作区。
#
# 用法:
#   ./start-cli.sh                            # REPL 交互模式
#   ./start-cli.sh "帮我写一个排序函数"         # 单次提问模式
#   AGENT_WORKSPACE=/other/path ./start-cli.sh # 指定工作区

set -euo pipefail

# ── 定位项目根目录 ──────────────────────────────────
ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── 调用者所在目录作为默认工作区 ────────────────────
DEFAULT_WORKSPACE="${AGENT_WORKSPACE:-$(pwd)}"

# ── 启动 CLI ──────────────────────────────────────
cd "$ROOT/backend"
exec env AGENT_WORKSPACE="$DEFAULT_WORKSPACE" uv run python cli.py "$@"
