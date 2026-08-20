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

# JSON 回退列表（用于 watchlist 表为空时）
_WATCHLIST_FROM_JSON: list[str] = [_to_futu_code(item) for item in _WATCHLIST_ITEMS]
_WATCHLIST_DETAIL_FROM_JSON: list[dict] = [
    {**item, "futu_code": _to_futu_code(item)} for item in _WATCHLIST_ITEMS
]


def get_watchlist() -> list[str]:
    """从 SQLite 读取活跃标的列表。表为空时回退到 JSON。"""
    try:
        from trader_analysis.futu_strategy.watchlist_storage import get_all_codes, watchlist_count
        if watchlist_count() > 0:
            return get_all_codes()
    except Exception:
        pass
    return _WATCHLIST_FROM_JSON


def get_watchlist_detail() -> list[dict]:
    """从 SQLite 读取完整标的信息。表为空时回退到 JSON。"""
    try:
        from trader_analysis.futu_strategy.watchlist_storage import get_watchlist_detail as _get_detail, watchlist_count
        if watchlist_count() > 0:
            return _get_detail()
    except Exception:
        pass
    return _WATCHLIST_DETAIL_FROM_JSON


# 兼容属性：供现有模块继续使用 config.WATCHLIST
# 注意：这是动态属性，每次访问时从 DB 读取
class _WatchlistProxy(list):
    """透明代理，访问时动态读取 DB。"""
    def __iter__(self):
        return iter(get_watchlist())
    def __len__(self):
        return len(get_watchlist())
    def __getitem__(self, idx):
        return get_watchlist()[idx]
    def __bool__(self):
        return bool(get_watchlist())


WATCHLIST = _WatchlistProxy()
WATCHLIST_DETAIL = _WATCHLIST_DETAIL_FROM_JSON  # API 层已改为从 DB 读，此处仅兼容

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
SCORE_STRONG_BUY: int = 80   # 强烈买入
SCORE_BUY: int = 60          # 买入

# 高置信度低估做多（daily-picks）筛选阈值：介于 BUY 和 STRONG_BUY 之间
# 需同时满足晨星低估 + 周线涨潮 + 日线回调
DAILY_PICKS_MIN_SCORE: int = 70

# ── K 线拉取配置 ──────────────────────────────────────────────────────────────
DAILY_KLINE_COUNT: int = 250   # 需 ≥ 200 根以计算 MA200，额外 50 根作为缓冲
WEEKLY_KLINE_COUNT: int = 60   # 约 14 个月的周线数据


# ── 交易设置 ───────────────────────────────────────────────────────────────────
# 是否允许对已持有标的加仓（金字塔加仓）
ALLOW_PYRAMID: bool = False

# ── 指标计算配置 ──────────────────────────────────────────────────────────────
# 日线指标配置（传入 250+ 根日线）
DAILY_INDICATOR_CONFIG: dict = {
    "ma": [5, 10, 20, 60, 120, 200, 250],
    "ema": [5, 10, 15, 20, 25, 30],
    "rsi": [6, 12, 24],
    "macd": {"fast": 12, "slow": 26, "signal": 9},
    "boll": {"length": 20, "std": 2},
    "vol_ma": [20],
    "atr": [14],
}

# 周线指标配置（传入 60+ 根周线）
WEEKLY_INDICATOR_CONFIG: dict = {
    "ema": [5, 10, 15, 20, 25, 30],
    "rsi": [6, 12, 24],
    "macd": {"fast": 12, "slow": 26, "signal": 9},
    "boll": {"length": 20, "std": 2},
}

# 4小时线指标配置（用于 EMA 飘带空转多/多转空信号）
FOUR_HOUR_INDICATOR_CONFIG: dict = {
    "ema": [5, 10, 15, 20, 25, 30],
    "rsi": [6, 12, 24],
    "macd": {"fast": 12, "slow": 26, "signal": 9},
    "atr": [14],
}

# 4H K 线初始拉取数量（3个月，每天约2根美股4H = ~130根）
INIT_4H_KLINE_COUNT: int = 150

# ── 持久化存储 ─────────────────────────────────────────────────────────────────
_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
# SQLite 数据库路径（通过环境变量 TA_DB_PATH 可覆盖）
DB_PATH: str = os.environ.get(
    "TA_DB_PATH", os.path.join(_PROJECT_ROOT, "data", "indicators.db")
)

# ── TP/SL 止盈止损配置 ─────────────────────────────────────────────────────
TPSL_ATR_PERIOD: int = 14
TPSL_ATR_MULTIPLIER: float = 2.0
TPSL_SWING_LOOKBACK: int = 60
TPSL_SWING_DISTANCE: int = 5
TPSL_MIN_RR_RATIO: float = 2.0

# ── 历史初始化拉取数量（仅 init_history.py 使用）────────────────────────────
INIT_DAILY_KLINE_COUNT: int = 1000   # API 单次上限
INIT_WEEKLY_KLINE_COUNT: int = 200   # 约 4 年周线数据

# ── 日志路径 ───────────────────────────────────────────────────────────────────
# 默认存放在项目根目录的 logs/ 下（通过环境变量 TA_LOG_DIR 可覆盖）
LOG_DIR: str = os.environ.get("TA_LOG_DIR", os.path.join(_PROJECT_ROOT, "logs"))
SCORE_LOG_FILE: str = os.path.join(LOG_DIR, "score_log.jsonl")
TRADE_LOG_FILE: str = os.path.join(LOG_DIR, "trade_log.jsonl")

# ── 市场温度（Market Temperature）─────────────────────────────────────────────
# 市场温度仅使用 SPY + QQQ 的技术面和价格位置（3 维度）
# VIX 期货由用户肉眼观察，不纳入算法
MARKET_TEMP_VOL_CODE: str = "US.VIXY"  # 保留定义供历史兼容，实际不再使用
MARKET_TEMP_CODES: list[str] = ["US.SPY", "US.QQQ"]

MARKET_TEMP_WEIGHTS: dict[str, float] = {
    "daily_tech": 0.50,
    "weekly_tech": 0.35,
    "price_pos": 0.15,
}

# ── 基本面分析 (Fundamental) ───────────────────────────────────────────────────
FUNDAMENTAL_FETCH_INTERVAL: float = 2.0  # yfinance 限频保护，每标的间隔2秒

FUNDAMENTAL_WEIGHTS: dict[str, int] = {
    "valuation_discount": 30,
    "pe_reasonability": 20,
    "growth": 20,
    "financial_health": 15,
    "analyst_consensus": 15,
}

FUNDAMENTAL_SIGNAL_UNDERVALUED: int = 75
FUNDAMENTAL_SIGNAL_OVERVALUED: int = 40

FUNDAMENTAL_SKIP_TICKERS: list[str] = ["QQQ", "SPY", "GLD", "IBIT", "07709", "VIXY", "VIX", "DRAM"]

# ── 顶背离检测配置 ────────────────────────────────────────────────────────────
TOP_DETECTION_CONFIG: dict = {
    # RSI 顶背离参数
    "rsi_divergence_lookback": 60,      # 回看 K 线根数
    "rsi_divergence_period": 6,         # 使用 RSI6
    "rsi_divergence_min_distance": 5,   # 两个峰之间最小间隔

    # 天量滞涨参数
    "volume_stall_multiplier": 2.0,     # 成交量超过 vol_ma20 的倍数
    "volume_stall_max_change": 0.02,    # 价格变动幅度阈值（2%以内视为滞涨）

    # MACD 顶背离参数
    "macd_divergence_lookback": 60,
    "macd_divergence_min_distance": 5,

    # 长上影线参数
    "upper_shadow_ratio": 0.6,          # 上影线占实体+上影线比例阈值
    "upper_shadow_consecutive": 2,      # 连续出现次数

    # 布林带收口参数
    "boll_squeeze_lookback": 10,        # 带宽变化率回看
    "boll_squeeze_threshold": -0.2,     # 带宽缩小 20% 视为收口

    # 加速赶顶参数
    "acceleration_short_window": 5,     # 短期斜率窗口
    "acceleration_long_window": 20,     # 长期斜率窗口
    "acceleration_ratio": 2.5,          # 短期斜率/长期斜率 > 此值视为加速

    # 前高距离参数
    "near_high_lookback": 120,          # 回看根数（约半年）
    "near_high_threshold": 0.05,        # 距前高 5% 以内
}

# ── 减仓执行配置 ─────────────────────────────────────────────────────────────
SELL_CONFIG: dict = {
    # 减仓比例
    "sell_1_ratio": 1 / 3,     # 第一刀：减总仓位的 1/3
    "sell_2_ratio": 2 / 3,     # 第二刀：减剩余仓位的 2/3
    "sell_3_ratio": 1.0,       # 第三刀：清仓（留 keep_min_qty 股观察）
    "keep_min_qty": 1,          # 最少保留股数（底仓观察）

    # 紧急止损参数
    "emergency_drop_pct": 0.07,     # 单日跌幅 > 7% 立即清仓
    "emergency_ma_period": 20,      # 跌破 MA20 立即清仓

    # 第二刀确认参数
    "ma5_break_confirm_days": 1,    # 跌破 MA5 确认天数（收盘价低于 MA5）

    # 第三刀确认参数
    "ma5_recovery_days": 2,         # 连续 N 日未站回 MA5 → 触发第三刀
}

# ── 底部信号检测配置 ────────────────────────────────────────────────────────────
BOTTOM_DETECTION_CONFIG: dict = {
    # 支撑位检测参数
    "support_ma_periods": [20, 30, 50, 60],     # 检测这些均线作为支撑
    "near_support_threshold": 0.02,              # 距均线 2% 以内视为"附近"

    # 深V检测参数（日内跌破支撑后收回）
    "deep_v_shadow_dominant": True,              # 下影线 > 上影线

    # 缩量参数
    "volume_shrink_ratio": 0.7,                  # 成交量 < vol_ma20 * 此值 视为缩量
    "volume_shrink_days": 3,                     # 连续 N 日缩量

    # RSI 底背离参数
    "rsi_divergence_lookback": 60,
    "rsi_divergence_period": 6,
    "rsi_divergence_min_distance": 5,

    # W底形态参数
    "w_bottom_lookback": 30,                     # W底回看窗口
    "w_bottom_price_tolerance": 0.03,            # 两个低点价差容忍度（3%以内视为平行底）

    # 支撑确认参数
    "support_confirm_next_day_up": True,         # 背离后次日收盘高于前日

    # 站上MA5参数
    "reclaim_ma5_confirm_days": 1,               # 收盘站上MA5确认天数
}

