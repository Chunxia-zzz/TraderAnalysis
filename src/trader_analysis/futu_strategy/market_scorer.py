"""市场温度评分模块。

按**指数**独立评估情绪冷热：SPY 与 QQQ 各一套三维温度，各给各的状态与仓位建议。
评分越高=越恐慌=越值得加仓，评分越低=越贪婪=应减仓。
（2026-10-19 镜像反转：与个股评分 total_score 同向，高分=机会，子项均为「越恐慌分越高」）

维度：日线技术面(50%) + 周线技术面(35%) + 价格位置(15%)
两个指数**共用同一套阈值**，因此两个分数可跨指数直接比较，差值即「温差」。

> 2026-11-10 起口径变更：原先 SPY 与 QQQ 在每个维度上各占 50% 合并成一个「大盘温度」，
> 分化被抹平。现已拆为两个独立温度；合并值退役，`market_score` 表只保留历史、不再写入。
> 个股评分的「恐慌加成」仍取两指数温度的平均，以保持 `total_score` 与变更前等价。

数据来源：完全从 storage 读取已入库的 K 线 + 指标，不调用 Futu API。
"""

from __future__ import annotations

import logging

import pandas as pd

from trader_analysis.futu_strategy import market_clock, storage

logger = logging.getLogger(__name__)

# ── 状态文案映射（高分=恐慌=加仓，2026-10-19 镜像反转）────────────────────────
_STATUS_LEVELS: list[tuple[float, str, str]] = [
    (95, "极端恐慌", "融资+期权超配"),
    (85, "极度恐慌", "重仓逆势买入"),
    (70, "偏悲观", "积极加仓"),
    (55, "略偏冷", "适度加仓"),
    (45, "中性", "维持仓位"),
    (30, "略偏热", "适度减仓"),
    (15, "偏贪婪", "积极减仓"),
    (0, "极度贪婪", "大幅减仓"),
]

NEUTRAL_SCORE = 50.0


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _percentile_rank(series: pd.Series, current: float, lookback: int) -> float:
    """当前值在最近 lookback 个值中的百分位排名，返回 0~1。"""
    window = series.tail(lookback).dropna()
    if len(window) < 10:
        return 0.5  # 数据不足 10 根，中性
    return float((window < current).sum()) / len(window)


def _calc_pct_b(close: float, upper: float, lower: float) -> float:
    """从存储的布林带列计算 %B。"""
    if pd.isna(upper) or pd.isna(lower) or upper == lower:
        return 0.5
    return (close - lower) / (upper - lower)


def _map_status(composite: float) -> tuple[str, str]:
    """综合评分 → (市场状态文案, 操作建议)。高分=恐慌=加仓方向。"""
    for threshold, label, action in _STATUS_LEVELS:
        if composite >= threshold:
            return label, action
    return "极度贪婪", "大幅减仓"


def _map_position(composite: float, heavy_extreme: bool, light_extreme: bool) -> float:
    """仓位映射纯函数: 30% ~ 120%（高分=恐慌=高仓位）。

    与 2026-10-19 反转前旧口径逐位等价（composite_new = 100 - composite_old）：
      heavy: 旧 100+(15-c_old)*20/15 ≡ 新 100+(c_new-85)*20/15
      light: 旧 85+(25-c_old)*1.5  ≡ 新 85+(c_new-75)*1.5
      normal: 旧 85-(c_old-25)*55/75 ≡ 新 30+c_new*55/75
    """
    if heavy_extreme:
        # composite 85->100 映射到 100->120%
        return _clamp(100 + (composite - 85) * (20.0 / 15), 100, 120)
    if light_extreme:
        # composite 75->85 映射到 85->100%
        return _clamp(85 + (composite - 75) * (15.0 / 10), 85, 100)
    # 正常区: composite 0->75 映射到 30->85%
    return _clamp(30 + composite * (55.0 / 75), 30, 85)



def _safe_score(fn, *args, dimension_name: str) -> dict:
    """安全调用维度评分函数，失败时返回中性分 50。"""
    try:
        result = fn(*args)
        if result is None:
            raise ValueError("scorer returned None")
        return result
    except Exception as exc:
        logger.warning(f"{dimension_name} 计算失败: {exc}，使用中性评分 50")
        return {"score": NEUTRAL_SCORE, "breakdown": {"error": str(exc)}}


# ── 单资产温度评分（黄金 / BTC）────────────────────────────────────────────────

_ASSET_CONFIGS: dict[str, dict] = {
    "GLD": {
        "label":              "黄金",
        "code_daily":         "US.GLD",
        "code_weekly":        "US.GLD",
        "ath_drawdown_zero":  0.25,   # 回撤 25% → 0 分（黄金正常回调幅度较大）
        "ma200_range":        0.20,   # MA200 偏离映射区间 ±20%
    },
    "BTC": {
        "label":              "比特币 (IBIT)",
        "code_daily":         "US.IBIT",
        "code_weekly":        "US.IBIT",
        "ath_drawdown_zero":  0.50,   # 回撤 50% → 0 分（BTC 腰斩为常态）
        "ma200_range":        0.60,   # MA200 偏离映射区间 ±60%
        "note":               "IBIT 上市于2024年初，历史样本有限，百分位置信度较低",
    },
}


def _score_asset_daily(df: pd.DataFrame, cfg: dict) -> dict:
    """单资产日线技术面：RSI + MACD 百分位 + 布林 %B，三项平均。越恐慌分越高。"""
    last = df.iloc[-1]
    scores, breakdown = [], {}

    rsi = float(last.get("rsi6", 50))
    rsi_score = _clamp(100 - int(rsi / 10) * 10.0)
    scores.append(rsi_score)
    breakdown["daily_rsi"] = round(rsi, 1)
    breakdown["daily_rsi_score"] = round(rsi_score, 1)

    macd_current = float(last.get("macd", 0))
    macd_pct = _percentile_rank(df["macd"].dropna(), macd_current, 252)
    macd_score = (1 - macd_pct) * 100
    scores.append(macd_score)
    breakdown["daily_macd_score"] = round(macd_score, 1)

    pct_b = _calc_pct_b(
        float(last.get("close", 0)),
        float(last.get("boll_upper", 0)),
        float(last.get("boll_lower", 0)),
    )
    bb_score = _clamp((1 - pct_b) * 100)
    scores.append(bb_score)
    breakdown["daily_bb_pctB"] = round(pct_b, 3)
    breakdown["daily_bb_score"] = round(bb_score, 1)

    return {"score": sum(scores) / len(scores), "breakdown": breakdown}


def _score_asset_weekly(df: pd.DataFrame, cfg: dict) -> dict:
    """单资产周线技术面：RSI + MACD 百分位 + 布林 %B，三项平均。越恐慌分越高。"""
    last = df.iloc[-1]
    scores, breakdown = [], {}

    rsi = float(last.get("rsi6", 50))
    rsi_score = _clamp(100 - int(rsi / 10) * 10.0)
    scores.append(rsi_score)
    breakdown["weekly_rsi"] = round(rsi, 1)
    breakdown["weekly_rsi_score"] = round(rsi_score, 1)

    macd_current = float(last.get("macd", 0))
    macd_pct = _percentile_rank(df["macd"].dropna(), macd_current, 52)
    macd_score = (1 - macd_pct) * 100
    scores.append(macd_score)
    breakdown["weekly_macd_score"] = round(macd_score, 1)

    pct_b = _calc_pct_b(
        float(last.get("close", 0)),
        float(last.get("boll_upper", 0)),
        float(last.get("boll_lower", 0)),
    )
    bb_score = _clamp((1 - pct_b) * 100)
    scores.append(bb_score)
    breakdown["weekly_bb_pctB"] = round(pct_b, 3)
    breakdown["weekly_bb_score"] = round(bb_score, 1)

    return {"score": sum(scores) / len(scores), "breakdown": breakdown}


def _score_asset_price_position(df: pd.DataFrame, cfg: dict) -> dict:
    """单资产价格位置：52w 高低位 + ATH 回撤 + MA200 偏离，三项平均。越恐慌分越高。"""
    scores, breakdown = [], {}
    current_price = float(df.iloc[-1]["close"])

    # 52 周位置（位置越低分越高）
    recent_252 = df.tail(252)
    high_52w = float(recent_252["high"].max())
    low_52w  = float(recent_252["low"].min())
    pos_52w  = (current_price - low_52w) / (high_52w - low_52w) if high_52w > low_52w else 0.5
    score_52w = _clamp((1 - pos_52w) * 100)
    scores.append(score_52w)
    breakdown["pos_52w"]   = round(pos_52w, 3)
    breakdown["score_52w"] = round(score_52w, 1)

    # ATH 回撤（回撤越深分越高；满分线按资产类型调整）
    ath = float(df["high"].max())
    drawdown  = (ath - current_price) / ath if ath > 0 else 0
    ath_zero  = cfg["ath_drawdown_zero"]
    ath_score = _clamp(drawdown / ath_zero * 100)
    scores.append(ath_score)
    breakdown["ath_drawdown"] = round(drawdown, 4)
    breakdown["ath_score"]    = round(ath_score, 1)

    # MA200 偏离（偏离越负分越高；映射区间按资产类型调整）
    closes   = df["close"].dropna()
    ma_range = cfg["ma200_range"]
    if len(closes) >= 200:
        ma200     = float(closes.tail(200).mean())
        deviation = (current_price - ma200) / ma200
    else:
        ma200     = float(closes.mean())
        deviation = 0.0
    ma200_score = _clamp((ma_range - deviation) / (2 * ma_range) * 100)
    scores.append(ma200_score)
    breakdown["ma200_dev"]   = round(deviation, 4)
    breakdown["ma200_score"] = round(ma200_score, 1)

    return {"score": sum(scores) / len(scores), "breakdown": breakdown}


def compute_asset_temperature(asset_key: str) -> dict | None:
    """
    计算单资产（GLD / BTC）的温度评分。

    与大盘温度共用三维度框架，但阈值按资产波动特性独立校准。
    完全从 storage 读取，无需 Futu OpenD。

    Returns:
        结果字典，数据不足时返回 None。
    """
    cfg = _ASSET_CONFIGS.get(asset_key)
    if not cfg:
        logger.warning(f"未知资产 key: {asset_key}")
        return None

    daily_df  = storage.query_recent(cfg["code_daily"],  "1d", limit=300)
    weekly_df = storage.query_recent(cfg["code_weekly"], "1w", limit=60)

    if daily_df.empty:
        logger.warning(f"{asset_key} 日线数据为空")
        return None

    weights = {"daily_tech": 0.50, "weekly_tech": 0.35, "price_pos": 0.15}

    daily_tech = _safe_score(
        _score_asset_daily, daily_df, cfg, dimension_name=f"{asset_key} 日线技术面"
    )
    if not weekly_df.empty:
        weekly_tech = _safe_score(
            _score_asset_weekly, weekly_df, cfg, dimension_name=f"{asset_key} 周线技术面"
        )
    else:
        weekly_tech = {"score": NEUTRAL_SCORE, "breakdown": {"error": "周线数据不足"}}
    price_pos = _safe_score(
        _score_asset_price_position, daily_df, cfg, dimension_name=f"{asset_key} 价格位置"
    )

    composite = (
        daily_tech["score"]  * weights["daily_tech"]
        + weekly_tech["score"] * weights["weekly_tech"]
        + price_pos["score"]   * weights["price_pos"]
    )

    market_status, action_suggestion = _map_status(composite)
    last = daily_df.iloc[-1]
    weekly_rsi = float(weekly_df.iloc[-1].get("rsi6", 50)) if not weekly_df.empty else None

    return {
        "label":              cfg["label"],
        "code":               cfg["code_daily"],
        "composite_score":    round(composite, 1),
        "market_status":      market_status,
        "action_suggestion":  action_suggestion,
        "price":              round(float(last["close"]), 2),
        "daily_rsi":          round(float(last.get("rsi6", 0)), 1),
        "weekly_rsi":         round(weekly_rsi, 1) if weekly_rsi is not None else None,
        "ma200_dev":          price_pos["breakdown"].get("ma200_dev"),
        "ath_drawdown":       price_pos["breakdown"].get("ath_drawdown"),
        "pos_52w":            price_pos["breakdown"].get("pos_52w"),
        "daily_tech_score":   round(daily_tech["score"], 1),
        "weekly_tech_score":  round(weekly_tech["score"], 1),
        "price_score":        round(price_pos["score"], 1),
        "note":               cfg.get("note"),
    }


def compute_asset_temperature_history(asset_key: str, days: int = 60) -> list[dict]:
    """
    计算单资产（GLD / BTC）历史温度评分序列。

    对最近 days 个交易日做滑窗切片，每天独立计算一次温度评分，
    与 `compute_index_temperature_history` 同一套滑窗 + 周线定稿守卫，完全从 storage 读取。

    Returns:
        按日期升序的 [{"date": ..., "composite_score": ...}, ...] 列表
    """
    cfg = _ASSET_CONFIGS.get(asset_key)
    if not cfg:
        return []

    read_limit = days + 300
    daily_all  = storage.query_recent(cfg["code_daily"],  "1d", limit=read_limit)
    weekly_all = storage.query_recent(cfg["code_weekly"], "1w", limit=days + 100)

    if daily_all.empty:
        return []

    weights = {"daily_tech": 0.50, "weekly_tech": 0.35, "price_pos": 0.15}
    total_rows = len(daily_all)
    min_rows = 60
    backfill_count = min(days, total_rows - min_rows)
    if backfill_count <= 0:
        return []

    history = []
    for i in range(backfill_count, 0, -1):
        end_idx = total_rows - i + 1
        daily_df = daily_all.iloc[:end_idx].copy()
        current_date = str(daily_df.iloc[-1].get("date", ""))

        # 周线在 as_of 当日是否已定稿（周线 date 记周一，周五收盘才成立）
        weekly_df = market_clock.filter_week_closed(weekly_all, current_date)

        try:
            dt = _safe_score(_score_asset_daily, daily_df, cfg, dimension_name="")
            if not weekly_df.empty:
                wt = _safe_score(_score_asset_weekly, weekly_df, cfg, dimension_name="")
            else:
                wt = {"score": NEUTRAL_SCORE, "breakdown": {}}
            pp = _safe_score(_score_asset_price_position, daily_df, cfg, dimension_name="")

            composite = (
                dt["score"] * weights["daily_tech"]
                + wt["score"] * weights["weekly_tech"]
                + pp["score"] * weights["price_pos"]
            )
            history.append({"date": current_date, "composite_score": round(composite, 1)})
        except Exception as exc:
            logger.debug(f"compute_asset_temperature_history {asset_key} {current_date}: {exc}")

    return history


# ── 指数温度（SPY / QQQ，2026-11-10 拆分）─────────────────────────────────────
#
# 阈值刻意写成两个配置里相同的数值：**两个指数共用一套**（spec FR-002），因此
#   ① 两个温度分数可跨指数直接比大小；
#   ② 差值（温差 = SPY − QQQ）有明确含义：负值 = 标普温度更低 = 标普相对更强。
# 若将来要给 QQQ 单独放宽区间，必须先改 specs/003 的 FR-002，不能只改这两个数字。

_INDEX_CONFIGS: dict[str, dict] = {
    "SPY": {
        "label": "标普 500",
        "code_daily": "US.SPY",
        "code_weekly": "US.SPY",
        "ath_drawdown_zero": 0.15,
        "ma200_range": 0.15,
    },
    "QQQ": {
        "label": "纳斯达克 100",
        "code_daily": "US.QQQ",
        "code_weekly": "US.QQQ",
        "ath_drawdown_zero": 0.15,
        "ma200_range": 0.15,
    },
}

INDEX_KEYS: tuple[str, ...] = ("SPY", "QQQ")

# 温差历史的最早日期：更早的合并数据不做拆分回算（spec FR-007）
SPREAD_HISTORY_START = "2025-01-01"

_INDEX_WEIGHTS = {"daily_tech": 0.50, "weekly_tech": 0.35, "price_pos": 0.15}


def _index_insufficient(key: str, score_date: str, reason: str) -> dict:
    """单指数数据不足时的降级结果：只降级自己，不伪造中性分（spec FR-013）。"""
    cfg = _INDEX_CONFIGS[key]
    return {
        "key": key,
        "code": cfg["code_daily"],
        "label": cfg["label"],
        "date": score_date,
        "data_insufficient": True,
        "reason": reason,
        "composite_score": None,
        "target_position_pct": None,
        "market_status": "数据不足",
        "action_suggestion": "—",
        "extreme_triggered": False,
        "extreme_level": "none",
        "leverage_tool": "none",
        "dimensions": [],
        "indicators": {},
        "detail": {"error": reason},
    }


def _build_index_result(
    key: str,
    score_date: str,
    daily_tech: dict,
    weekly_tech: dict,
    price_pos: dict,
    daily_df: pd.DataFrame,
) -> dict:
    """把三维度结果组装成单个指数的温度记录（纯函数）。"""
    cfg = _INDEX_CONFIGS[key]
    composite = (
        daily_tech["score"] * _INDEX_WEIGHTS["daily_tech"]
        + weekly_tech["score"] * _INDEX_WEIGHTS["weekly_tech"]
        + price_pos["score"] * _INDEX_WEIGHTS["price_pos"]
    )

    last = daily_df.iloc[-1]
    daily_rsi = float(last.get("rsi6", 50))
    weekly_rsi = (
        float(weekly_tech["breakdown"].get("weekly_rsi"))
        if weekly_tech["breakdown"].get("weekly_rsi") is not None
        else None
    )

    # 极端层：按**该指数自己**的 RSI 判定，不沿用合并期的结论
    heavy_extreme = (
        composite >= 85
        and daily_rsi < 30
        and weekly_rsi is not None
        and weekly_rsi < 30
    )
    light_extreme = composite >= 75 and not heavy_extreme
    extreme_level = "heavy" if heavy_extreme else ("light" if light_extreme else "none")

    target_position = _map_position(composite, heavy_extreme, light_extreme)
    leverage_tool = "none"
    if target_position > 100:
        leverage_tool = "margin + OTM_call"
    elif target_position > 90:
        leverage_tool = "margin"

    market_status, action_suggestion = _map_status(composite)

    detail: dict = {}
    for dim in (daily_tech, weekly_tech, price_pos):
        detail.update(dim.get("breakdown", {}))

    bb_pct_b = daily_tech["breakdown"].get("daily_bb_pctB", 0.5)

    return {
        "key": key,
        "code": cfg["code_daily"],
        "label": cfg["label"],
        "date": score_date,
        "data_insufficient": False,
        "composite_score": round(composite, 1),
        "target_position_pct": round(target_position, 1),
        "market_status": market_status,
        "action_suggestion": action_suggestion,
        "extreme_triggered": bool(heavy_extreme or light_extreme),
        "extreme_level": extreme_level,
        "leverage_tool": leverage_tool,
        "dimensions": [
            {
                "key": "daily_tech",
                "label": "日线技术面",
                "score": round(daily_tech["score"], 1),
                "weight": _INDEX_WEIGHTS["daily_tech"],
            },
            {
                "key": "weekly_tech",
                "label": "周线技术面",
                "score": round(weekly_tech["score"], 1),
                "weight": _INDEX_WEIGHTS["weekly_tech"],
            },
            {
                "key": "price_position",
                "label": "价格位置",
                "score": round(price_pos["score"], 1),
                "weight": _INDEX_WEIGHTS["price_pos"],
            },
        ],
        "indicators": {
            "price": round(float(last["close"]), 2),
            "daily_rsi": round(daily_rsi, 1),
            "weekly_rsi": round(weekly_rsi, 1) if weekly_rsi is not None else None,
            "ma200_dev": price_pos["breakdown"].get("ma200_dev"),
            "ath_drawdown": price_pos["breakdown"].get("ath_drawdown"),
            "pos_52w": price_pos["breakdown"].get("pos_52w"),
            "bb_pct_b": bb_pct_b,
        },
        "detail": detail,
    }


def compute_index_temperature(index_key: str) -> dict | None:
    """计算单个指数（SPY / QQQ）最新一天的温度，完全从 storage 读取。

    Returns:
        温度记录；未知 key 返回 None；数据不足返回 data_insufficient=True 的记录。
    """
    cfg = _INDEX_CONFIGS.get(index_key)
    if not cfg:
        logger.warning(f"未知指数 key: {index_key}")
        return None

    daily_df = storage.query_recent(cfg["code_daily"], "1d", limit=300)
    weekly_df = storage.query_recent(cfg["code_weekly"], "1w", limit=60)

    if daily_df.empty:
        return _index_insufficient(index_key, "", f"{cfg['code_daily']} 日线数据为空")

    score_date = str(daily_df.iloc[-1].get("date", ""))

    daily_tech = _safe_score(
        _score_asset_daily, daily_df, cfg, dimension_name=f"{index_key} 日线技术面"
    )
    if weekly_df.empty:
        weekly_tech = {"score": NEUTRAL_SCORE, "breakdown": {}}
        logger.warning(f"{index_key} 周线数据为空，周线维度按中性 50 计")
    else:
        weekly_tech = _safe_score(
            _score_asset_weekly, weekly_df, cfg, dimension_name=f"{index_key} 周线技术面"
        )
    price_pos = _safe_score(
        _score_asset_price_position, daily_df, cfg, dimension_name=f"{index_key} 价格位置"
    )

    return _build_index_result(
        index_key, score_date, daily_tech, weekly_tech, price_pos, daily_df
    )


def compute_temperature_spread(spy_score: float | None, qqq_score: float | None) -> float | None:
    """温差 = SPY 温度 − QQQ 温度。负值代表标普温度更低（标普相对更强）。"""
    if spy_score is None or qqq_score is None:
        return None
    return round(float(spy_score) - float(qqq_score), 1)


def spread_label(value: float | None) -> str:
    """温差的展示文案。符号语义只在这里定义一次，前端不得自行拼。"""
    if value is None:
        return "数据不足"
    if value < 0:
        return "标普相对更强"
    if value > 0:
        return "纳指相对更强"
    return "两者均衡"


def compute_index_temperature_history(
    index_key: str,
    start_date: str | None = None,
    days: int | None = None,
) -> list[dict]:
    """计算单个指数的历史温度序列。

    Parameters:
        start_date: 起始日期（含），默认 2025-01-01；更早的日期一律不返回（FR-007）
        days:       若给出，则取最近 days 个交易日（与 start_date 二选一，days 优先）

    Returns:
        按日期升序的 [{"date", "composite_score", "target_position_pct"}, ...]
    """
    cfg = _INDEX_CONFIGS.get(index_key)
    if not cfg:
        return []

    daily_all = storage.query_recent(cfg["code_daily"], "1d", limit=1500)
    weekly_all = storage.query_recent(cfg["code_weekly"], "1w", limit=600)
    if daily_all.empty:
        return []

    dates = [str(d) for d in daily_all["date"]]

    if days is not None:
        start_idx = max(0, len(dates) - int(days))
    else:
        floor = start_date or SPREAD_HISTORY_START
        start_idx = next((i for i, d in enumerate(dates) if d >= floor), None)
        if start_idx is None:
            return []

    # 至少 60 根才能算有意义的百分位；起点之前的历史本身用于缓冲，不需要额外截断
    history: list[dict] = []
    for i in range(start_idx, len(dates)):
        daily_df = daily_all.iloc[: i + 1]
        current_date = dates[i]
        weekly_df = market_clock.filter_week_closed(weekly_all, current_date)

        try:
            dt = _safe_score(_score_asset_daily, daily_df, cfg, dimension_name="")
            wt = (
                _safe_score(_score_asset_weekly, weekly_df, cfg, dimension_name="")
                if not weekly_df.empty
                else {"score": NEUTRAL_SCORE, "breakdown": {}}
            )
            pp = _safe_score(_score_asset_price_position, daily_df, cfg, dimension_name="")

            composite = (
                dt["score"] * _INDEX_WEIGHTS["daily_tech"]
                + wt["score"] * _INDEX_WEIGHTS["weekly_tech"]
                + pp["score"] * _INDEX_WEIGHTS["price_pos"]
            )
            daily_rsi = float(daily_df.iloc[-1].get("rsi6", 50))
            weekly_rsi = wt["breakdown"].get("weekly_rsi")
            heavy = (
                composite >= 85
                and daily_rsi < 30
                and weekly_rsi is not None
                and weekly_rsi < 30
            )
            light = composite >= 75 and not heavy
            history.append(
                {
                    "date": current_date,
                    "composite_score": round(composite, 1),
                    "target_position_pct": round(_map_position(composite, heavy, light), 1),
                }
            )
        except Exception as exc:  # noqa: BLE001 - 单日失败不该中断整条序列
            logger.debug(f"compute_index_temperature_history {index_key} {current_date}: {exc}")

    return history


def compute_spread_history(
    start_date: str | None = None,
    days: int | None = None,
) -> list[dict]:
    """温差序列：逐日 SPY 温度 − QQQ 温度。缺失日期跳过，不插值（FR-007）。"""
    spy_hist = compute_index_temperature_history("SPY", start_date=start_date, days=days)
    qqq_hist = compute_index_temperature_history("QQQ", start_date=start_date, days=days)

    qqq_by_date = {p["date"]: p["composite_score"] for p in qqq_hist}
    spread: list[dict] = []
    for point in spy_hist:
        qqq_score = qqq_by_date.get(point["date"])
        if qqq_score is None:
            continue
        value = compute_temperature_spread(point["composite_score"], qqq_score)
        spread.append({"date": point["date"], "value": value})
    return spread


def calculate_index_temperatures() -> dict:
    """计算两个指数的最新温度并落库（幂等），返回聚合结果供 CLI / 调用方使用。"""
    storage.init_db()

    results: dict[str, dict | None] = {}
    for key in INDEX_KEYS:
        result = compute_index_temperature(key)
        results[key] = result
        if result and not result.get("data_insufficient"):
            storage.upsert_market_temp_split(result["date"], result["code"], result)

    spy_score = results["SPY"]["composite_score"] if results.get("SPY") else None
    qqq_score = results["QQQ"]["composite_score"] if results.get("QQQ") else None
    value = compute_temperature_spread(spy_score, qqq_score)

    return {
        "date": (results.get("SPY") or results.get("QQQ") or {}).get("date", ""),
        "indexes": [results[k] for k in INDEX_KEYS if results.get(k)],
        "spread": {"value": value, "label": spread_label(value)},
    }


def backfill_index_temperatures(
    start_date: str | None = None,
    days: int | None = None,
) -> int:
    """回算两个指数的历史温度并落库，返回写入行数。

    默认起点 2025-01-01；更早的合并历史不做拆分（spec Assumptions）。
    """
    storage.init_db()

    written = 0
    for key in INDEX_KEYS:
        for point in compute_index_temperature_history(key, start_date=start_date, days=days):
            storage.upsert_market_temp_split_point(key, point)
            written += 1
    logger.info(f"指数温度回算完成，写入 {written} 行")
    return written
