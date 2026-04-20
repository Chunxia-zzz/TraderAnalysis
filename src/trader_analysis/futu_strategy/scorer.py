"""评分引擎。

从已经过 indicators.calc_indicators() 计算的 DataFrame 中读取指标值，
做阈值判断并加权评分，输出 0~100 总分及信号等级。

本模块 **不做任何指标计算**，只做"读值 → 比较阈值 → 打分"。

各指标权重（合计 100 分）：
  C1  周线 RSI < 30              22 分
  C2  日线 MACD 柱线底背离       16 分
  C3  VIX > 30                   12 分
  C4  布林带下轨附近/以下        10 分
  C5  日线 RSI < 30              10 分
  C6  CNN Fear & Greed < 25      10 分
  C7  恐慌放量后缩量              8 分
  C8  周线 MACD 柱线缩小          6 分
  C9  价格偏离 MA250 > 8%         6 分
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from trader_analysis.futu_strategy.indicators import (
    detect_macd_divergence,
    detect_panic_volume,
)

# ── 单项评分函数 ──────────────────────────────────────────────────────────────
# 每个函数返回 {"score": int, "value": ..., "triggered": bool}

def _check_weekly_rsi(w: pd.Series) -> dict:
    """C1: 周线 RSI14 < 30 → 22 分。"""
    val = w.get("rsi14")
    if pd.isna(val):
        return {"score": 0, "value": None, "triggered": False}
    triggered = float(val) < 30.0
    return {"score": 22 if triggered else 0, "value": round(float(val), 2), "triggered": triggered}


def _check_daily_macd_divergence(daily_df: pd.DataFrame) -> dict:
    """C2: 日线 MACD 柱线底背离 → 16 分。"""
    triggered = detect_macd_divergence(daily_df)
    return {"score": 16 if triggered else 0, "triggered": triggered}


def _check_vix(vix: float | None) -> dict:
    """C3: VIX > 30 → 12 分。"""
    if vix is None:
        return {"score": 0, "value": None, "triggered": False}
    triggered = vix > 30.0
    return {"score": 12 if triggered else 0, "value": round(vix, 2), "triggered": triggered}


def _check_boll_lower(d: pd.Series) -> dict:
    """C4: 收盘价 ≤ 布林下轨 × 1.02 → 10 分。"""
    close_val = d.get("close")
    lower_val = d.get("boll_lower")
    if pd.isna(close_val) or pd.isna(lower_val) or lower_val == 0:
        return {"score": 0, "value": None, "triggered": False}
    triggered = float(close_val) <= float(lower_val) * 1.02
    score = 10 if triggered else 0
    return {"score": score, "value": round(float(lower_val), 2), "triggered": triggered}


def _check_daily_rsi(d: pd.Series) -> dict:
    """C5: 日线 RSI14 < 30 → 10 分。"""
    val = d.get("rsi14")
    if pd.isna(val):
        return {"score": 0, "value": None, "triggered": False}
    triggered = float(val) < 30.0
    return {"score": 10 if triggered else 0, "value": round(float(val), 2), "triggered": triggered}


def _check_fear_greed(fg: float | None) -> dict:
    """C6: CNN F&G < 25 → 10 分。"""
    if fg is None:
        return {"score": 0, "value": None, "triggered": False}
    triggered = fg < 25.0
    return {"score": 10 if triggered else 0, "value": round(fg, 2), "triggered": triggered}


def _check_panic_volume(daily_df: pd.DataFrame) -> dict:
    """C7: 恐慌放量后缩量 → 8 分。"""
    triggered = detect_panic_volume(daily_df)
    return {"score": 8 if triggered else 0, "triggered": triggered}


def _check_weekly_macd_shrinking(weekly_df: pd.DataFrame) -> dict:
    """C8: 周线 MACD 柱线为负且绝对值缩小 → 6 分。"""
    if len(weekly_df) < 2:
        return {"score": 0, "value": None, "triggered": False}
    w = weekly_df.iloc[-1]
    w_prev = weekly_df.iloc[-2]
    macd_val = w.get("macd")
    prev_macd = w_prev.get("macd")
    if pd.isna(macd_val) or pd.isna(prev_macd):
        return {"score": 0, "value": None, "triggered": False}
    triggered = float(macd_val) < 0 and abs(float(macd_val)) < abs(float(prev_macd))
    return {"score": 6 if triggered else 0, "triggered": triggered}


def _check_ma250_deviation(d: pd.Series) -> dict:
    """C9: 价格偏离 MA250 超过 8% → 6 分。"""
    ma_val = d.get("ma250")
    close_val = d.get("close")
    if pd.isna(ma_val) or pd.isna(close_val) or ma_val == 0:
        return {"score": 0, "value": None, "triggered": False}
    deviation = (float(ma_val) - float(close_val)) / float(ma_val)
    triggered = deviation > 0.08
    return {"score": 6 if triggered else 0, "value": round(deviation, 4), "triggered": triggered}


# ── 汇总评分 ──────────────────────────────────────────────────────────────────

def calculate_score(
    code: str,
    daily_df: pd.DataFrame,
    weekly_df: pd.DataFrame,
    *,
    vix: float | None,
    fg: float | None,
) -> dict:
    """汇总所有指标，返回评分结果字典。

    Parameters
    ----------
    code      : 标的代码
    daily_df  : 已经过 calc_indicators() 计算的日线 DataFrame
    weekly_df : 已经过 calc_indicators() 计算的周线 DataFrame
    vix       : VIX 当前值（来自 external_data）
    fg        : CNN F&G 评分（来自 external_data，None 表示获取失败）

    Returns
    -------
    {
        "code": "US.AAPL",
        "total_score": 78,
        "signal": "BUY",
        "breakdown": { ... },
        "timestamp": "2026-04-14 06:01:00"
    }
    """
    d = daily_df.iloc[-1]
    w = weekly_df.iloc[-1]

    breakdown = {
        "weekly_rsi": _check_weekly_rsi(w),
        "daily_macd_divergence": _check_daily_macd_divergence(daily_df),
        "vix": _check_vix(vix),
        "boll_lower": _check_boll_lower(d),
        "daily_rsi": _check_daily_rsi(d),
        "cnn_fg": _check_fear_greed(fg),
        "panic_volume": _check_panic_volume(daily_df),
        "weekly_macd_shrink": _check_weekly_macd_shrinking(weekly_df),
        "ma250_deviation": _check_ma250_deviation(d),
    }

    total_score = sum(v["score"] for v in breakdown.values())

    from trader_analysis.futu_strategy import config

    if total_score >= config.SCORE_STRONG_BUY:
        signal = "STRONG_BUY"
    elif total_score >= config.SCORE_BUY:
        signal = "BUY"
    else:
        signal = "NO_ACTION"

    return {
        "code": code,
        "total_score": total_score,
        "signal": signal,
        "breakdown": breakdown,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
