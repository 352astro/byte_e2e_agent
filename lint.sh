#!/usr/bin/env bash
#
# 一键 Lint 前后端。
#
# 用法:
#   ./lint.sh           # lint only
#   ./lint.sh --fix     # lint + auto-fix
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
FIX=false
if [[ "${1:-}" == "--fix" ]]; then
    FIX=true
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
echo -e "${CYAN}=== Summary ===${NC}"
echo -e "  Passed: ${GREEN}$pass_count${NC}  Failed: ${RED}$fail_count${NC}"

if [[ "$fail_count" -gt 0 ]]; then
    exit 1
fi
