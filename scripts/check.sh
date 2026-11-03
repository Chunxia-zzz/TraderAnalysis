#!/usr/bin/env bash
# 本地预检脚本 —— 与 CI（.github/workflows/ci.yml 的 check job）完全同源。
#
# 用法：
#   bash scripts/check.sh           # lint 变更文件 + 全量测试（推送到 GitHub 前跑）
#   bash scripts/check.sh --all     # lint 全部 src/tests + 全量测试（存量债 burn-down 用）
#
# 环境变量：
#   PYTHON    解释器；默认自动探测 .venv（Windows: Scripts/python.exe；POSIX: bin/python），
#             找不到再用 PATH 里的 python（CI runner 走这条）。
#   BASE_REF  lint 基线（默认 origin/main；CI 由 workflow 注入 github.event.before）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# ── 解释器探测 ──────────────────────────────────────────────────────────────
if [ -z "${PYTHON:-}" ]; then
  if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
    PYTHON="$ROOT/.venv/Scripts/python.exe"
  elif [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
  else
    PYTHON=python
  fi
fi

# ── ruff：存量债只 lint 变更文件，新代码必须干净 ────────────────────────────
# 全库当前有 282 条存量违规（以 E501 为主），一次清零属于跨模块重构，另行排期。
# CI 与本脚本保持同一条门槛：merge-base 之后新增/修改的 .py 必须过 ruff。
if [ "${1:-}" = "--all" ]; then
  "$PYTHON" -m ruff check src tests
else
  BASE_REF="${BASE_REF:-origin/main}"
  # 用命令替换而不是进程替换：git diff 失败时退出码会传播，set -e 直接终止，
  # 避免「lint 静默跳过、流水线假绿」（ci-onboarding 速查表：假绿退出码）。
  DIFF_OUT="$(git diff --name-only --diff-filter=ACMR "$BASE_REF...HEAD" -- '*.py')"
  if [ -z "$DIFF_OUT" ]; then
    echo "No changed Python files vs ${BASE_REF}; skip ruff."
  else
    mapfile -t FILES <<< "$DIFF_OUT"
    echo "lint targets:"
    printf '  %s\n' "${FILES[@]}"
    "$PYTHON" -m ruff check "${FILES[@]}"
  fi
fi

# ── 全量测试（唯一既有门槛，本地 97 项全绿）────────────────────────────────
"$PYTHON" -m pytest -q
