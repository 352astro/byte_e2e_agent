#!/usr/bin/env bash
#
# 一键 Lint 前后端。
#
# 用法:
#   ./lint.sh                 # 全量
#   ./lint.sh --backend       # 仅后端
#   ./lint.sh --frontend      # 仅前端
#   ./lint.sh --fix           # 全量 + auto-fix
#   ./lint.sh --backend --fix # 后端 + auto-fix
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
FIX=false
RUN_BACKEND=false
RUN_FRONTEND=false

for arg in "$@"; do
    case "$arg" in
        --fix)      FIX=true ;;
        --backend)  RUN_BACKEND=true ;;
        --frontend) RUN_FRONTEND=true ;;
        --all)      RUN_BACKEND=true; RUN_FRONTEND=true ;;
        *)          echo "Unknown flag: $arg"; exit 1 ;;
    esac
done

# Default: run both
if ! $RUN_BACKEND && ! $RUN_FRONTEND; then
    RUN_BACKEND=true
    RUN_FRONTEND=true
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

pass_count=0
fail_count=0

check() {
    local label="$1"
    local ok="$2"
    if [[ "$ok" == "true" ]]; then
        echo -e "  ${GREEN}✓${NC} $label"
        pass_count=$((pass_count + 1))
    else
        echo -e "  ${RED}✗${NC} $label"
        fail_count=$((fail_count + 1))
    fi
}

# ── Backend ──────────────────────────────────────────

if $RUN_BACKEND; then
    echo -e "${CYAN}=== Backend (ruff) ===${NC}"
    cd "$ROOT/backend"
    if $FIX; then
        uv run ruff check . --fix && uv run ruff format . 2>&1
        check "ruff check --fix + format" true
    else
        if uv run ruff check . 2>&1; then
            check "ruff check" true
        else
            check "ruff check" false
        fi
        if uv run ruff format . --check 2>&1; then
            check "ruff format --check" true
        else
            check "ruff format --check" false
        fi
    fi
    echo ""
fi

# ── Frontend ─────────────────────────────────────────

if $RUN_FRONTEND; then
    echo -e "${CYAN}=== Frontend (eslint) ===${NC}"
    cd "$ROOT/frontend"
    if $FIX; then
        npm run lint -- --fix 2>&1
        check "eslint --fix" true
    else
        if npm run lint 2>&1; then
            check "eslint" true
        else
            check "eslint" false
        fi
    fi
    echo ""
fi

# ── Summary ──────────────────────────────────────────

echo -e "${CYAN}=== Summary ===${NC}"
echo -e "  Passed: ${GREEN}$pass_count${NC}  Failed: ${RED}$fail_count${NC}"

if [[ "$fail_count" -gt 0 ]]; then
    exit 1
fi
