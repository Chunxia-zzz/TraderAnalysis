"""评分引擎（v4 — 连续评分 + 回撤因子 + 大盘温度加成）。

从已入库的 K 线指标 DataFrame 读值，通过连续映射函数计算各维度得分（0~1），
加权求和输出 0~100 总分及信号等级。

纯本地评分，不依赖任何外部 API。

6 维度 + 权重（合计 100）：
  C1  周线 RSI6          20  —— (80 - rsi) / 60
  C2  日线 MACD 百分位    20  —— 1 - percentile_rank(252)
  C3  布林带 %B          15  —— 1 - %B
  C4  日线 RSI6          20  —— (80 - rsi) / 60
  C5  周线 MACD 百分位    10  —— 1 - percentile_rank(52)
  C6  60日回撤           15  —— (drawdown - 0.05) / 0.20

大盘温度加成：composite < 40 时最多 +15 分。
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd


# ── 权重配置 ──────────────────────────────────────────────────────────────────

WEIGHTS: dict[str, int] = {
    "weekly_rsi": 20,
    "daily_macd_pct": 20,
    "boll_position": 15,
    "daily_rsi": 20,
    "weekly_macd_pct": 10,
    "drawdown": 15,
}


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _percentile_rank(series: pd.Series, current: float, lookback: int) -> float:
    """当前值在最近 lookback 个值中的百分位排名，返回 0~1。"""
    window = series.tail(lookback).dropna()
    if len(window) < 10:
        return 0.5
    return float((window < current).sum()) / len(window)


# ── 单项评分函数 ──────────────────────────────────────────────────────────────
# 每个函数返回 {"score": float(0~weight), "raw": float, "ratio": float(0~1)}


def _score_weekly_rsi(weekly_df: pd.DataFrame) -> dict:
    """C1: 周线 RSI6 连续映射。RSI=20→满分，RSI≥80→0分。"""
    w = weekly_df.iloc[-1]
    val = w.get("rsi6")
    if pd.isna(val):
        return {"score": 0.0, "raw": None, "ratio": 0.0}
    rsi = float(val)
    ratio = _clamp((80 - rsi) / 60)
    score = ratio * WEIGHTS["weekly_rsi"]
    return {"score": round(score, 1), "raw": round(rsi, 1), "ratio": round(ratio, 3)}


def _score_daily_macd_pct(daily_df: pd.DataFrame) -> dict:
    """C2: 日线 MACD 百分位（反转）。百分位越低=动量越弱=得分越高。"""
    macd_series = daily_df["macd"].dropna()
    if len(macd_series) < 10:
        return {"score": 0.0, "raw": None, "ratio": 0.0}
    current = float(macd_series.iloc[-1])
    pct = _percentile_rank(macd_series, current, 252)
    ratio = _clamp(1 - pct)
    score = ratio * WEIGHTS["daily_macd_pct"]
    return {"score": round(score, 1), "raw": round(pct, 3), "ratio": round(ratio, 3)}


def _score_boll_position(daily_df: pd.DataFrame) -> dict:
    """C3: 布林带 %B（反转）。%B=0(下轨)→满分，%B=1(上轨)→0分。"""
    d = daily_df.iloc[-1]
    close = d.get("close")
    upper = d.get("boll_upper")
    lower = d.get("boll_lower")
    if pd.isna(close) or pd.isna(upper) or pd.isna(lower) or upper == lower:
        return {"score": 0.0, "raw": None, "ratio": 0.0}
    pct_b = (float(close) - float(lower)) / (float(upper) - float(lower))
    ratio = _clamp(1 - pct_b)
    score = ratio * WEIGHTS["boll_position"]
    return {"score": round(score, 1), "raw": round(pct_b, 3), "ratio": round(ratio, 3)}


def _score_daily_rsi(daily_df: pd.DataFrame) -> dict:
    """C4: 日线 RSI6 连续映射。RSI=20→满分，RSI≥80→0分。"""
    d = daily_df.iloc[-1]
    val = d.get("rsi6")
    if pd.isna(val):
        return {"score": 0.0, "raw": None, "ratio": 0.0}
    rsi = float(val)
    ratio = _clamp((80 - rsi) / 60)
    score = ratio * WEIGHTS["daily_rsi"]
    return {"score": round(score, 1), "raw": round(rsi, 1), "ratio": round(ratio, 3)}


def _score_weekly_macd_pct(weekly_df: pd.DataFrame) -> dict:
    """C5: 周线 MACD 百分位（反转）。百分位越低=周线动量越弱=得分越高。"""
    macd_series = weekly_df["macd"].dropna()
    if len(macd_series) < 10:
        return {"score": 0.0, "raw": None, "ratio": 0.0}
    current = float(macd_series.iloc[-1])
    pct = _percentile_rank(macd_series, current, 52)
    ratio = _clamp(1 - pct)
    score = ratio * WEIGHTS["weekly_macd_pct"]
    return {"score": round(score, 1), "raw": round(pct, 3), "ratio": round(ratio, 3)}


def _score_drawdown(daily_df: pd.DataFrame) -> dict:
    """C6: 60日回撤因子。从60日高点回撤5%开始给分，25%满分。对强势股回调有效。"""
    d = daily_df.iloc[-1]
    close_val = d.get("close")
    if pd.isna(close_val):
        return {"score": 0.0, "raw": None, "ratio": 0.0}
    close = float(close_val)
    high_60d = float(daily_df.tail(60)["high"].max())
    if high_60d <= 0:
        return {"score": 0.0, "raw": 0.0, "ratio": 0.0}
    drawdown = (high_60d - close) / high_60d
    # 回撤 <5% 不给分（正常波动），5%~25% 线性给分
    ratio = _clamp((drawdown - 0.05) / 0.20)
    score = ratio * WEIGHTS["drawdown"]
    return {"score": round(score, 1), "raw": round(drawdown, 4), "ratio": round(ratio, 3)}


# ── 汇总评分 ──────────────────────────────────────────────────────────────────


def calculate_score(
    code: str,
    daily_df: pd.DataFrame,
    weekly_df: pd.DataFrame,
    market_composite: float | None = None,
) -> dict:
    """汇总所有维度，返回评分结果字典。

    纯本地评分，只从已入库的 K 线指标 DataFrame 计算。

    Parameters
    ----------
    code              : 标的代码
    daily_df          : 已含指标的日线 DataFrame
    weekly_df         : 已含指标的周线 DataFrame
    market_composite  : 当日大盘温度评分（可选，用于恐慌加成）

    Returns
    -------
    {
        "code": "US.AAPL",
        "total_score": 45.2,
        "signal": "NO_ACTION",
        "breakdown": { ... },
        "market_bonus": 5.2,
        "timestamp": "2026-05-05 20:00:00"
    }
    """
    breakdown = {
        "weekly_rsi": _score_weekly_rsi(weekly_df),
        "daily_macd_pct": _score_daily_macd_pct(daily_df),
        "boll_position": _score_boll_position(daily_df),
        "daily_rsi": _score_daily_rsi(daily_df),
        "weekly_macd_pct": _score_weekly_macd_pct(weekly_df),
        "drawdown": _score_drawdown(daily_df),
    }

    base_score = round(sum(v["score"] for v in breakdown.values()), 1)

    # 大盘温度加成：composite < 40 时最多加 15 分
    market_bonus = 0.0
    if market_composite is not None and market_composite < 40:
        market_bonus = round(_clamp((40 - market_composite) / 40) * 15, 1)

    total_score = min(100.0, round(base_score + market_bonus, 1))

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
        "market_bonus": market_bonus,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
