"""市场温度评分模块。

通过 3 个维度加权评估市场情绪冷热程度，输出综合评分（0~100）及目标仓位建议。
评分越低=越恐慌=应加仓，评分越高=越贪婪=应减仓。

维度：日线技术面(50%) + 周线技术面(35%) + 价格位置(15%)
数据来源：完全从 storage 读取已入库的 K 线 + 指标，不调用 Futu API。
"""

from __future__ import annotations

import logging
from datetime import date as dt_date

import numpy as np
import pandas as pd

from trader_analysis.futu_strategy import config, storage

logger = logging.getLogger(__name__)

# ── 状态文案映射 ──────────────────────────────────────────────────────────────
_STATUS_LEVELS: list[tuple[float, str, str]] = [
    (5, "极端恐慌", "融资+期权超配"),
    (15, "极度恐慌", "重仓逆势买入"),
    (30, "偏悲观", "积极加仓"),
    (45, "略偏冷", "适度加仓"),
    (55, "中性", "维持仓位"),
    (70, "略偏热", "适度减仓"),
    (85, "偏贪婪", "积极减仓"),
    (100, "极度贪婪", "大幅减仓"),
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
    """综合评分 → (市场状态文案, 操作建议)。"""
    for threshold, label, action in _STATUS_LEVELS:
        if composite <= threshold:
            return label, action
    return "极度贪婪", "大幅减仓"


# ── 维度 1：日线技术面 (50%) ──────────────────────────────────────────────────


def _score_daily_tech(spy_df: pd.DataFrame, qqq_df: pd.DataFrame) -> dict:
    """
    SPY + QQQ 各 3 项：RSI score + MACD percentile + BB %B score。
    取 6 项算术平均。
    """
    scores = []
    breakdown = {}

    for label, df in [("SPY", spy_df), ("QQQ", qqq_df)]:
        last = df.iloc[-1]
        # RSI score: 分档制，每 10 点一档（<10→0, 10-20→10, ..., >90→100）
        rsi = float(last.get("rsi6", 50))
        rsi_score = _clamp(int(rsi / 10) * 10.0)
        scores.append(rsi_score)
        breakdown[f"{label}_RSI"] = round(rsi, 1)
        breakdown[f"{label}_RSI_score"] = round(rsi_score, 1)

        # MACD histogram percentile (lookback=252)
        macd_series = df["macd"].dropna()
        macd_current = float(last.get("macd", 0))
        macd_pct = _percentile_rank(macd_series, macd_current, 252)
        macd_score = macd_pct * 100
        scores.append(macd_score)
        breakdown[f"{label}_MACD_score"] = round(macd_score, 1)

        # Bollinger %B score: clamp(%B * 100)
        close = float(last.get("close", 0))
        upper = float(last.get("boll_upper", 0))
        lower = float(last.get("boll_lower", 0))
        pct_b = _calc_pct_b(close, upper, lower)
        bb_score = _clamp(pct_b * 100)
        scores.append(bb_score)
        breakdown[f"{label}_BB_pctB"] = round(pct_b, 3)
        breakdown[f"{label}_BB_score"] = round(bb_score, 1)

    final = sum(scores) / len(scores) if scores else NEUTRAL_SCORE
    return {"score": final, "breakdown": breakdown}


# ── 维度 2：周线技术面 (35%) ──────────────────────────────────────────────────


def _score_weekly_tech(spy_weekly: pd.DataFrame, qqq_weekly: pd.DataFrame) -> dict:
    """
    SPY + QQQ 各 3 项：周线 RSI score + 周线 MACD percentile + 周线 BB %B。
    取 6 项算术平均。
    """
    scores = []
    breakdown = {}

    for label, df in [("SPY", spy_weekly), ("QQQ", qqq_weekly)]:
        last = df.iloc[-1]
        # Weekly RSI score: 分档制，每 10 点一档（<10→0, 10-20→10, ..., >90→100）
        rsi = float(last.get("rsi6", 50))
        rsi_score = _clamp(int(rsi / 10) * 10.0)
        scores.append(rsi_score)
        breakdown[f"{label}_Weekly_RSI"] = round(rsi, 1)
        breakdown[f"{label}_Weekly_RSI_score"] = round(rsi_score, 1)

        # Weekly MACD histogram percentile (lookback=52)
        macd_series = df["macd"].dropna()
        macd_current = float(last.get("macd", 0))
        macd_pct = _percentile_rank(macd_series, macd_current, 52)
        macd_score = macd_pct * 100
        scores.append(macd_score)
        breakdown[f"{label}_Weekly_MACD_score"] = round(macd_score, 1)

        # Weekly Bollinger %B score: clamp(%B * 100)
        close = float(last.get("close", 0))
        upper = float(last.get("boll_upper", 0))
        lower = float(last.get("boll_lower", 0))
        pct_b = _calc_pct_b(close, upper, lower)
        bb_score = _clamp(pct_b * 100)
        scores.append(bb_score)
        breakdown[f"{label}_Weekly_BB_pctB"] = round(pct_b, 3)
        breakdown[f"{label}_Weekly_BB_score"] = round(bb_score, 1)

    final = sum(scores) / len(scores) if scores else NEUTRAL_SCORE
    return {"score": final, "breakdown": breakdown}


# ── 维度 3：价格位置 (15%) ───────────────────────────────────────────────────


def _score_price_position(spy_df: pd.DataFrame, qqq_df: pd.DataFrame) -> dict:
    """
    SPY + QQQ 各 3 项：52w 位置 + ATH 回撤 + MA200 偏离度。
    取 6 项算术平均。
    """
    scores = []
    breakdown = {}

    for label, df in [("SPY", spy_df), ("QQQ", qqq_df)]:
        current_price = float(df.iloc[-1]["close"])
        breakdown[f"{label}_price"] = round(current_price, 2)

        # 52-week position: from last 252 bars
        recent_252 = df.tail(252)
        high_52w = float(recent_252["high"].max())
        low_52w = float(recent_252["low"].min())
        if high_52w > low_52w:
            pos_52w = (current_price - low_52w) / (high_52w - low_52w)
        else:
            pos_52w = 0.5
        score_52w = _clamp(pos_52w * 100)
        scores.append(score_52w)
        breakdown[f"{label}_52w_score"] = round(score_52w, 1)

        # ATH drawdown: max(high) across ALL stored bars
        # 零分线 15%：大盘回撤 15% 即为极端恐慌（SPY 正常回调 5-10%）
        ath = float(df["high"].max())
        drawdown = (ath - current_price) / ath if ath > 0 else 0
        ath_score = _clamp((1 - drawdown / 0.15) * 100)
        scores.append(ath_score)
        breakdown[f"{label}_ATH_drawdown"] = round(drawdown, 4)
        breakdown[f"{label}_ATH_score"] = round(ath_score, 1)

        # MA200 deviation
        # 映射区间 [-15%, +15%] → [0, 100]：大盘偏离 MA200 超过 15% 即为极端
        closes = df["close"].dropna()
        if len(closes) >= 200:
            ma200 = float(closes.tail(200).mean())
            deviation = (current_price - ma200) / ma200
        else:
            ma200 = float(closes.mean())
            deviation = 0.0
        ma200_score = _clamp((deviation + 0.15) / 0.30 * 100)
        scores.append(ma200_score)
        breakdown[f"{label}_MA200_dev"] = round(deviation, 4)
        breakdown[f"{label}_MA200_score"] = round(ma200_score, 1)

    final = sum(scores) / len(scores) if scores else NEUTRAL_SCORE
    return {"score": final, "breakdown": breakdown}




# ── 主入口 ────────────────────────────────────────────────────────────────────


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


def _compute_score(
    spy_daily: pd.DataFrame,
    qqq_daily: pd.DataFrame,
    gld_daily: pd.DataFrame,
    vix_daily: pd.DataFrame,
    spy_weekly: pd.DataFrame,
    qqq_weekly: pd.DataFrame,
    score_date: str,
) -> dict:
    """核心评分计算（纯函数，接受已切片的 DataFrame）。"""
    weights = config.MARKET_TEMP_WEIGHTS

    has_spy = not spy_daily.empty
    has_qqq = not qqq_daily.empty
    has_spy_w = not spy_weekly.empty
    has_qqq_w = not qqq_weekly.empty

    # 计算各维度
    if has_spy and has_qqq:
        daily_tech = _safe_score(_score_daily_tech, spy_daily, qqq_daily, dimension_name="日线技术面")
    else:
        daily_tech = {"score": NEUTRAL_SCORE, "breakdown": {"error": "SPY/QQQ 日线数据不足"}}

    if has_spy_w and has_qqq_w:
        weekly_tech = _safe_score(_score_weekly_tech, spy_weekly, qqq_weekly, dimension_name="周线技术面")
    else:
        weekly_tech = {"score": NEUTRAL_SCORE, "breakdown": {"error": "SPY/QQQ 周线数据不足"}}

    if has_spy and has_qqq:
        price_pos = _safe_score(_score_price_position, spy_daily, qqq_daily, dimension_name="价格位置")
    else:
        price_pos = {"score": NEUTRAL_SCORE, "breakdown": {"error": "SPY/QQQ 日线数据不足"}}

    # 加权综合评分（3 维度：日线技术面 + 周线技术面 + 价格位置）
    composite = (
        daily_tech["score"] * weights["daily_tech"]
        + weekly_tech["score"] * weights["weekly_tech"]
        + price_pos["score"] * weights["price_pos"]
    )

    # 极端层判断
    spy_daily_rsi = float(spy_daily.iloc[-1].get("rsi6", 50)) if has_spy else 50
    spy_weekly_rsi = float(spy_weekly.iloc[-1].get("rsi6", 50)) if has_spy_w else 50

    # 极端层判断（两级）
    heavy_extreme = (
        composite <= 15
        and spy_daily_rsi < 30
        and spy_weekly_rsi < 30
    )
    light_extreme = composite <= 25 and not heavy_extreme

    extreme_triggered = heavy_extreme or light_extreme

    # 仓位映射: 30% ~ 120%
    if heavy_extreme:
        # composite 15->0 映射到 100->120%
        target_position = _clamp(100 + (15 - composite) * (20.0 / 15), 100, 120)
    elif light_extreme:
        # composite 25->15 映射到 85->100%
        target_position = _clamp(85 + (25 - composite) * (15.0 / 10), 85, 100)
    else:
        # 正常区: composite 25->100 映射到 85->30%
        target_position = _clamp(85 - (composite - 25) * (55.0 / 75), 30, 85)

    # 杠杆工具建议
    leverage_tool = "none"
    if target_position > 100:
        leverage_tool = "margin + OTM_call"
    elif target_position > 90:
        leverage_tool = "margin"

    # 极端层级别标记
    extreme_level = "heavy" if heavy_extreme else ("light" if light_extreme else "none")

    # 状态文案
    market_status, action_suggestion = _map_status(composite)

    # 组装维度列表
    dimensions = [
        {"key": "daily_tech", "label": "日线技术面", "score": round(daily_tech["score"], 1), "weight": weights["daily_tech"]},
        {"key": "weekly_tech", "label": "周线技术面", "score": round(weekly_tech["score"], 1), "weight": weights["weekly_tech"]},
        {"key": "price_position", "label": "价格位置", "score": round(price_pos["score"], 1), "weight": weights["price_pos"]},
    ]

    # 组装指标摘要
    indicators = {}
    if has_spy:
        spy_last = spy_daily.iloc[-1]
        spy_vol_ratio = float(spy_last["volume"]) / float(spy_last["vol_ma20"]) if float(spy_last.get("vol_ma20", 0)) > 0 else 1.0
        indicators["SPY"] = {
            "price": round(float(spy_last["close"]), 2),
            "daily_rsi": round(float(spy_last.get("rsi6", 0)), 1),
            "weekly_rsi": round(spy_weekly_rsi, 1),
            "ma200_dev": round(price_pos["breakdown"].get("SPY_MA200_dev", 0), 4),
            "vol_ratio": round(spy_vol_ratio, 2),
            "bb_pct_b": round(daily_tech["breakdown"].get("SPY_BB_pctB", 0.5), 3),
        }
    if has_qqq:
        qqq_last = qqq_daily.iloc[-1]
        qqq_vol_ratio = float(qqq_last["volume"]) / float(qqq_last["vol_ma20"]) if float(qqq_last.get("vol_ma20", 0)) > 0 else 1.0
        qqq_w_rsi = float(qqq_weekly.iloc[-1].get("rsi6", 50)) if has_qqq_w else 50
        indicators["QQQ"] = {
            "price": round(float(qqq_last["close"]), 2),
            "daily_rsi": round(float(qqq_last.get("rsi6", 0)), 1),
            "weekly_rsi": round(qqq_w_rsi, 1),
            "ma200_dev": round(price_pos["breakdown"].get("QQQ_MA200_dev", 0), 4),
            "vol_ratio": round(qqq_vol_ratio, 2),
            "bb_pct_b": round(daily_tech["breakdown"].get("QQQ_BB_pctB", 0.5), 3),
        }

    # 合并所有维度 breakdown 为 detail
    detail = {}
    for dim in [daily_tech, weekly_tech, price_pos]:
        detail.update(dim.get("breakdown", {}))

    return {
        "date": score_date,
        "composite_score": round(composite, 1),
        "target_position_pct": round(target_position, 1),
        "extreme_triggered": extreme_triggered,
        "extreme_level": extreme_level,
        "leverage_tool": leverage_tool,
        "market_status": market_status,
        "action_suggestion": action_suggestion,
        "dimensions": dimensions,
        "indicators": indicators,
        "detail": detail,
        "daily_tech_score": round(daily_tech["score"], 1),
        "weekly_tech_score": round(weekly_tech["score"], 1),
        "vol_score": None,
        "price_score": round(price_pos["score"], 1),
        "volume_score": None,
        "safe_haven_score": None,
        "spy_price": indicators.get("SPY", {}).get("price"),
        "qqq_price": indicators.get("QQQ", {}).get("price"),
        "gld_price": None,
        "vix_value": None,
        "spy_daily_rsi": indicators.get("SPY", {}).get("daily_rsi"),
        "qqq_daily_rsi": indicators.get("QQQ", {}).get("daily_rsi"),
        "spy_weekly_rsi": indicators.get("SPY", {}).get("weekly_rsi"),
        "qqq_weekly_rsi": indicators.get("QQQ", {}).get("weekly_rsi"),
        "spy_ma200_dev": indicators.get("SPY", {}).get("ma200_dev"),
        "qqq_ma200_dev": indicators.get("QQQ", {}).get("ma200_dev"),
        "spy_vol_ratio": indicators.get("SPY", {}).get("vol_ratio"),
        "qqq_vol_ratio": indicators.get("QQQ", {}).get("vol_ratio"),
    }


def calculate_market_temperature() -> dict:
    """
    计算最新一天的市场温度评分并持久化。

    完全从 storage 读取已入库的 K 线+指标数据。
    """
    storage.init_db()

    spy_daily = storage.query_recent("US.SPY", "1d", limit=300)
    qqq_daily = storage.query_recent("US.QQQ", "1d", limit=300)
    gld_daily = storage.query_recent("US.GLD", "1d", limit=300)
    vix_daily = storage.query_recent(config.MARKET_TEMP_VOL_CODE, "1d", limit=300)
    spy_weekly = storage.query_recent("US.SPY", "1w", limit=60)
    qqq_weekly = storage.query_recent("US.QQQ", "1w", limit=60)

    score_date = str(dt_date.today())
    if not spy_daily.empty:
        last_date = spy_daily.iloc[-1].get("date")
        if last_date:
            score_date = str(last_date)

    result = _compute_score(spy_daily, qqq_daily, gld_daily, vix_daily, spy_weekly, qqq_weekly, score_date)
    storage.upsert_market_score(score_date, result)
    return result


def backfill_market_temperature(days: int = 60) -> int:
    """
    回溯计算历史市场温度评分。

    从已入库的 K 线数据中，逐日切片计算过去 N 天的评分并写入 DB。
    需要至少 252 + days 天的日线数据才能保证百分位计算准确。

    Parameters:
        days: 回溯天数（默认 60 天）

    Returns:
        成功写入的天数
    """
    storage.init_db()
    logger.info(f"开始回溯计算市场温度，回溯 {days} 天")

    # 一次性读取所有可用数据（支持长历史回溯）
    read_limit = days + 300  # 回溯天数 + 百分位计算所需缓冲
    spy_daily_all = storage.query_recent("US.SPY", "1d", limit=read_limit)
    qqq_daily_all = storage.query_recent("US.QQQ", "1d", limit=read_limit)
    gld_daily_all = storage.query_recent("US.GLD", "1d", limit=read_limit)
    vix_daily_all = storage.query_recent(config.MARKET_TEMP_VOL_CODE, "1d", limit=read_limit)
    spy_weekly_all = storage.query_recent("US.SPY", "1w", limit=500)
    qqq_weekly_all = storage.query_recent("US.QQQ", "1w", limit=500)

    if spy_daily_all.empty:
        logger.warning("SPY 日线数据为空，无法回溯")
        return 0

    # 确定可回溯的日期范围
    # 至少需要 60 天数据才能计算有意义的百分位
    min_rows_needed = 60
    total_rows = len(spy_daily_all)
    backfill_count = min(days, total_rows - min_rows_needed)

    if backfill_count <= 0:
        logger.warning(f"数据不足，仅有 {total_rows} 行，需要至少 {min_rows_needed + 1} 行")
        return 0

    count = 0
    for i in range(backfill_count, 0, -1):
        # 切片：截止到倒数第 i 行（模拟"当天"只能看到截止到那天的数据）
        end_idx = total_rows - i + 1
        spy_daily = spy_daily_all.iloc[:end_idx].copy()
        qqq_daily = qqq_daily_all.iloc[:min(end_idx, len(qqq_daily_all))].copy()
        gld_daily = gld_daily_all.iloc[:min(end_idx, len(gld_daily_all))].copy()
        vix_daily = vix_daily_all.iloc[:min(end_idx, len(vix_daily_all))].copy()

        # 周线：找到日期 <= 当天的周线
        current_date = spy_daily.iloc[-1].get("date", "")
        spy_weekly = spy_weekly_all[spy_weekly_all["date"] <= current_date].copy()
        qqq_weekly = qqq_weekly_all[qqq_weekly_all["date"] <= current_date].copy()

        score_date = str(current_date)

        try:
            result = _compute_score(spy_daily, qqq_daily, gld_daily, vix_daily, spy_weekly, qqq_weekly, score_date)
            storage.upsert_market_score(score_date, result)
            count += 1
        except Exception as exc:
            logger.warning(f"回溯 {score_date} 失败: {exc}")

    logger.info(f"回溯完成，成功写入 {count} 天评分")
    return count
