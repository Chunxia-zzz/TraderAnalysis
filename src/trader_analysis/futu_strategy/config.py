"""策略配置。

修改此文件以自定义标的列表、仓位大小、评分阈值、OpenD 连接参数等。
"""

from __future__ import annotations

import json
import os

# ── OpenD 连接 ────────────────────────────────────────────────────────────────
OPEND_HOST: str = "127.0.0.1"
OPEND_PORT: int = 11111

# ── 监控标的列表 ──────────────────────────────────────────────────────────────
_PROJECT_ROOT_CFG = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
WATCHLIST_JSON_PATH: str = os.path.join(_PROJECT_ROOT_CFG, "data", "watchlist.json")


def _load_watchlist() -> tuple[list[dict], dict[str, str]]:
    """从 watchlist.json 加载标的池，返回 (items, categories)。"""
    with open(WATCHLIST_JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)
    categories = data.get("categories", {})
    items = data.get("watchlist", [])
    return items, categories


def _to_futu_code(item: dict) -> str:
    """将 JSON 条目转为 Futu 格式代码，如 US.SNDK、HK.07709。"""
    market = item["market"]
    ticker = item["ticker"]
    return f"{market}.{ticker}"


_WATCHLIST_ITEMS, WATCHLIST_CATEGORIES = _load_watchlist()

# Futu 格式代码列表，供 runner / init_history / daily_update 使用
WATCHLIST: list[str] = [_to_futu_code(item) for item in _WATCHLIST_ITEMS]

# 完整标的信息（带 futu_code 字段），供 API 层返回给前端
WATCHLIST_DETAIL: list[dict] = [
    {**item, "futu_code": _to_futu_code(item)} for item in _WATCHLIST_ITEMS
]

# ── 仓位配置 ───────────────────────────────────────────────────────────────────
POSITION_CONFIG: dict = {
    "STRONG_BUY": {
        "type": "fixed_amount",
        "amount_usd": 2000,  # 强烈买入：每次固定金额（USD）
    },
    "BUY": {
        "type": "fixed_amount",
        "amount_usd": 1000,  # 普通买入：每次固定金额（USD）
    },
}

# ── 评分阈值 ───────────────────────────────────────────────────────────────────
SCORE_STRONG_BUY: int = 90
SCORE_BUY: int = 70

# ── K 线拉取配置 ──────────────────────────────────────────────────────────────
DAILY_KLINE_COUNT: int = 250   # 需 ≥ 200 根以计算 MA200，额外 50 根作为缓冲
WEEKLY_KLINE_COUNT: int = 60   # 约 14 个月的周线数据

# ── 外部数据 ───────────────────────────────────────────────────────────────────
# CNN Fear & Greed 非官方接口
CNN_FG_URL: str = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
HTTP_TIMEOUT: int = 10  # 秒

# HTTP 代理（国内访问 CNN 可能需要，设为 None 则不使用）
# 示例：{"https": "http://127.0.0.1:7890"}
HTTP_PROXIES: dict | None = None

# VIX 行情代码；若 US.VIX 不可用可改为 "US.VIXY"
VIX_CODE: str = "US.VIX"

# ── 交易设置 ───────────────────────────────────────────────────────────────────
# 是否允许对已持有标的加仓（金字塔加仓）
ALLOW_PYRAMID: bool = False

# ── 指标计算配置 ──────────────────────────────────────────────────────────────
# 日线指标配置（传入 250+ 根日线）
DAILY_INDICATOR_CONFIG: dict = {
    "ma": [5, 10, 20, 60, 120, 250],
    "rsi": [14],
    "macd": {"fast": 12, "slow": 26, "signal": 9},
    "boll": {"length": 20, "std": 2},
    "vol_ma": [20],
}

# 周线指标配置（传入 60+ 根周线）
WEEKLY_INDICATOR_CONFIG: dict = {
    "rsi": [14],
    "macd": {"fast": 12, "slow": 26, "signal": 9},
}

# ── 持久化存储 ─────────────────────────────────────────────────────────────────
_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
# SQLite 数据库路径（通过环境变量 TA_DB_PATH 可覆盖）
DB_PATH: str = os.environ.get(
    "TA_DB_PATH", os.path.join(_PROJECT_ROOT, "data", "indicators.db")
)

# ── 历史初始化拉取数量（仅 init_history.py 使用）────────────────────────────
INIT_DAILY_KLINE_COUNT: int = 1000   # API 单次上限
INIT_WEEKLY_KLINE_COUNT: int = 200   # 约 4 年周线数据

# ── 日志路径 ───────────────────────────────────────────────────────────────────
# 默认存放在项目根目录的 logs/ 下（通过环境变量 TA_LOG_DIR 可覆盖）
LOG_DIR: str = os.environ.get("TA_LOG_DIR", os.path.join(_PROJECT_ROOT, "logs"))
SCORE_LOG_FILE: str = os.path.join(LOG_DIR, "score_log.jsonl")
TRADE_LOG_FILE: str = os.path.join(LOG_DIR, "trade_log.jsonl")
