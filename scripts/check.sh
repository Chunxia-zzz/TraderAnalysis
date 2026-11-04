#!/usr/bin/env bash
# 本地预检脚本 —— 与 CI（.github/workflows/ci.yml 的 check job）完全同源。
#
# 用法：
#   bash scripts/check.sh     # 全库 lint + 全量测试（含覆盖率门禁），push 前跑
#
# 环境变量：
#   PYTHON        解释器；默认自动探测 .venv（Windows: Scripts/python.exe；POSIX: bin/python），
#                 找不到再用 PATH 里的 python（CI runner 走这条）。
#   COV_FAIL_UNDER  覆盖率门禁阈值（总覆盖率）。默认 12（= CI 实测水位 15% − 3pp 余量；
#                 本地有真实 DB 时为 16%，多出的 1pp 来自空库 CI 会跳过的 5 项数据断言）。
#                 只能涨不能跌：本地或 CI 上看到的总覆盖率高于阈值时，可以把默认值上调。
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

# ── 项目必须已安装（可编辑安装），否则 pytest 收集期报 ModuleNotFoundError ──
# 首跑 CI 曾因此红掉（exit 2）：requirements-dev 只装依赖不装项目本身。
if ! "$PYTHON" -c "import trader_analysis" >/dev/null 2>&1; then
  echo "错误：当前解释器找不到 trader_analysis 包，请先安装项目：" >&2
  echo "  $PYTHON -m pip install -e ." >&2
  exit 1
fi

# ── ruff：全库门禁（2026-11-04 存量债清零后，从「变更文件」升级为全库）──────
"$PYTHON" -m ruff check src tests

# ── 全量测试 + 覆盖率门禁 ──────────────────────────────────────────────────
# 用「总覆盖率」而不是逐包阈值：单包覆盖率受平台分支（kill_unix/kill_windows 类）
# 与可选依赖在位与否影响，跨环境能差好几个点；总覆盖率把这些摊薄（ci-onboarding 实测规则）。
# 阈值 = CI 实测水位 − 3pp 余量，只能涨不能跌。
COV_FAIL_UNDER="${COV_FAIL_UNDER:-12}"
"$PYTHON" -m pytest -q \
  --cov=trader_analysis \
  --cov-report=term \
  --cov-fail-under="${COV_FAIL_UNDER}"

# 把实测总覆盖率写进 CI annotations（日志拿不到时也能核对各平台水位）
COV_TOTAL="$("$PYTHON" -m coverage report --format=total 2>/dev/null || true)"
if [ -n "$COV_TOTAL" ]; then
  echo "coverage total: ${COV_TOTAL}% (gate: ${COV_FAIL_UNDER}%)"
  echo "::notice::coverage total=${COV_TOTAL}% gate=${COV_FAIL_UNDER}%"
fi
