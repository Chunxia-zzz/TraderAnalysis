"""评分引擎。

汇总所有技术指标，返回 0~100 总分及信号等级。
指标计算统一调用 trader_analysis.indicators 模块的 calc_* 函数，
不重复实现数学逻辑。

各指标权重（合计 100 分）：
  周线 RSI < 30              22 分
  日线 MACD 柱线底背离       16 分
  布林带下轨附近/以下        10 分
  日线 RSI < 30              10 分
  VIX > 30                   12 分
  CNN Fear & Greed < 25      10 分
  周线 MACD 柱线缩小          6 分
  价格偏离 MA200 > 8%         6 分
  恐慌放量后缩量               8 分
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from trader_analysis.indicators import calc_bb_lower, calc_macd_hist, calc_rsi, calc_sma


# ── 内部工具函数 ──────────────────────────────────────────────────────────────

def _find_troughs(values: np.ndarray, distance: int = 5) -> np.ndarray:
    """查找局部最低点索引，优先使用 scipy，不可用时回退到纯 numpy 实现。"""
    try:
        from scipy.signal import find_peaks  # type: ignore[import]

        troughs, _ = find_peaks(-values, distance=distance)
        return troughs
    except ImportError:
        result: list[int] = []
        for i in range(1, len(values) - 1):
            if values[i] < values[i - 1] and values[i] < values[i + 1]:
                if not result or (i - result[-1]) >= distance:
                    result.append(i)
        return np.array(result, dtype=int)


# ── 单项指标评分函数 ──────────────────────────────────────────────────────────
# 每个函数返回 {"score": int, "value": float|None, "triggered": bool}

def _check_weekly_rsi(weekly_df: pd.DataFrame) -> dict:
    """周线 RSI14 < 30 → 22 分。"""
    close = weekly_df["close"].reset_index(drop=True)
    if len(close) < 15:
        return {"score": 0, "value": None, "triggered": False}
    rsi = calc_rsi(close)
    value = float(rsi.iloc[-1])
    if np.isnan(value):
        return {"score": 0, "value": None, "triggered": False}
    triggered = value < 30.0
    return {"score": 22 if triggered else 0, "value": round(value, 2), "triggered": triggered}


def _check_daily_rsi(daily_df: pd.DataFrame) -> dict:
    """日线 RSI14 < 30 → 10 分。"""
    close = daily_df["close"].reset_index(drop=True)
    if len(close) < 15:
        return {"score": 0, "value": None, "triggered": False}
    rsi = calc_rsi(close)
    value = float(rsi.iloc[-1])
    if np.isnan(value):
        return {"score": 0, "value": None, "triggered": False}
    triggered = value < 30.0
    return {"score": 10 if triggered else 0, "value": round(value, 2), "triggered": triggered}


def _check_daily_macd_divergence(daily_df: pd.DataFrame) -> dict:
    """日线 MACD 柱线底背离（价格新低但柱线未新低）→ 16 分。

    只检测最近 60 根 K 线内的背离，两个谷底间距 ≥ 5 根。
    """
    if len(daily_df) < 60:
        return {"score": 0, "value": None, "triggered": False}

    df60 = daily_df.iloc[-60:].reset_index(drop=True)
    close60 = df60["close"]
    low60 = df60["low"].values

    hist = calc_macd_hist(close60)
    hist_vals = hist.values

    troughs = _find_troughs(low60, distance=5)
    if len(troughs) < 2:
        return {"score": 0, "value": None, "triggered": False}

    idx1, idx2 = int(troughs[-2]), int(troughs[-1])
    price_new_low = low60[idx2] < low60[idx1]
    h1, h2 = hist_vals[idx1], hist_vals[idx2]
    hist_no_new_low = not (np.isnan(h1) or np.isnan(h2)) and h2 > h1

    triggered = bool(price_new_low and hist_no_new_low)
    return {"score": 16 if triggered else 0, "value": None, "triggered": triggered}


def _check_bollinger_lower(daily_df: pd.DataFrame) -> dict:
    """收盘价 ≤ 布林下轨 × 1.02 → 10 分。

    value 返回 close / lower_band 的比值（≤ 1.02 触发）。
    """
    close = daily_df["close"].reset_index(drop=True)
    if len(close) < 20:
        return {"score": 0, "value": None, "triggered": False}

    lower = calc_bb_lower(close)
    current_close = float(close.iloc[-1])
    lower_val = float(lower.iloc[-1])

    if np.isnan(lower_val) or lower_val == 0:
        return {"score": 0, "value": None, "triggered": False}

    ratio = current_close / lower_val
    triggered = ratio <= 1.02
    return {"score": 10 if triggered else 0, "value": round(ratio, 4), "triggered": triggered}


def _check_weekly_macd_shrinking(weekly_df: pd.DataFrame) -> dict:
    """周线 MACD 柱线为负且绝对值缩小（空头动能减弱）→ 6 分。"""
    close = weekly_df["close"].reset_index(drop=True)
    if len(close) < 36:  # 26（slow EMA）+ 9（signal）+ 1
        return {"score": 0, "value": None, "triggered": False}

    hist = calc_macd_hist(close)
    h_last = float(hist.iloc[-1])
    h_prev = float(hist.iloc[-2])

    if np.isnan(h_last) or np.isnan(h_prev):
        return {"score": 0, "value": None, "triggered": False}

    triggered = h_last < 0 and h_prev < 0 and abs(h_last) < abs(h_prev)
    return {"score": 6 if triggered else 0, "value": round(h_last, 4), "triggered": triggered}


def _check_ma200_deviation(daily_df: pd.DataFrame) -> dict:
    """价格在 MA200 下方超过 8% → 6 分。

    deviation = (MA200 - close) / MA200，正数表示价格低于均线。
    """
    close = daily_df["close"].reset_index(drop=True)
    if len(close) < 200:
        return {"score": 0, "value": None, "triggered": False}

    ma200 = calc_sma(close, 200)
    ma_val = float(ma200.iloc[-1])
    current_close = float(close.iloc[-1])

    if np.isnan(ma_val) or ma_val == 0:
        return {"score": 0, "value": None, "triggered": False}

    deviation = (ma_val - current_close) / ma_val
    triggered = deviation > 0.08
    return {"score": 6 if triggered else 0, "value": round(deviation, 4), "triggered": triggered}


def _check_vix(vix: float | None) -> dict:
    """VIX > 30 → 12 分。"""
    if vix is None:
        return {"score": 0, "value": None, "triggered": False}
    triggered = vix > 30.0
    return {"score": 12 if triggered else 0, "value": round(vix, 2), "triggered": triggered}


def _check_fear_greed(fg: float | None) -> dict:
    """CNN Fear & Greed < 25 → 10 分。"""
    if fg is None:
        return {"score": 0, "value": None, "triggered": False}
    triggered = fg < 25.0
    return {"score": 10 if triggered else 0, "value": round(fg, 2), "triggered": triggered}


def _check_panic_volume(daily_df: pd.DataFrame) -> dict:
    """恐慌放量后缩量 → 8 分。

    条件一：近 20 日内出现成交量 > 20 日均量 × 2 的峰值（恐慌日）。
    条件二：近 3 日均量 < 峰值日成交量 × 0.6（缩量确认）。
    value 返回 peak_vol / mean_vol 比值。
    """
    vol = daily_df["volume"].reset_index(drop=True)
    window = 20
    if len(vol) < window + 3:
        return {"score": 0, "value": None, "triggered": False}

    vol_window = vol.iloc[-window:]
    vol_mean = float(vol_window.mean())
    if vol_mean == 0:
        return {"score": 0, "value": None, "triggered": False}

    peak_pos = int(vol_window.values.argmax())
    peak_vol = float(vol_window.iloc[peak_pos])
    ratio = round(peak_vol / vol_mean, 2)

    is_panic = peak_vol > vol_mean * 2.0
    if not is_panic:
        return {"score": 0, "value": ratio, "triggered": False}

    peak_global_idx = len(vol) - window + peak_pos
    if len(vol) - 1 - peak_global_idx < 1:
        return {"score": 0, "value": ratio, "triggered": False}

    recent_3_mean = float(vol.iloc[-3:].mean())
    is_shrinking = recent_3_mean < peak_vol * 0.6

    triggered = is_panic and is_shrinking
    return {"score": 8 if triggered else 0, "value": ratio, "triggered": triggered}


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

    Returns
    -------
    {
        "code":        "US.AAPL",
        "total_score": 78,
        "signal":      "BUY",          # "STRONG_BUY" / "BUY" / "NO_ACTION"
        "breakdown": {
            "weekly_rsi":            {"score": 22, "value": 28.3, "triggered": True},
            "daily_macd_divergence": {"score": 0,  "value": None, "triggered": False},
            ...
        },
        "timestamp": "2026-04-14 06:01:00"
    }
    """
    breakdown = {
        "weekly_rsi":            _check_weekly_rsi(weekly_df),
        "daily_macd_divergence": _check_daily_macd_divergence(daily_df),
        "bollinger_lower":       _check_bollinger_lower(daily_df),
        "daily_rsi":             _check_daily_rsi(daily_df),
        "vix":                   _check_vix(vix),
        "fear_greed":            _check_fear_greed(fg),
        "weekly_macd_shrinking": _check_weekly_macd_shrinking(weekly_df),
        "ma200_deviation":       _check_ma200_deviation(daily_df),
        "panic_volume":          _check_panic_volume(daily_df),
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
