"""Take-Profit / Stop-Loss 计算模块。

纯计算模块：接收已含指标的 K 线 DataFrame，返回止盈/止损/风险回报结果。
不感知数据库、不做 HTTP 响应，由 API 层调用。

算法：
- 止损 = max(ATR止损, 支撑位止损) — 取较紧者
- 止盈 = min(阻力位, R:R目标) — 取较保守者
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
from scipy.signal import find_peaks


# ── ATR 计算（on-the-fly fallback）──────────────────────────────────────────

def _calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range (Wilder smoothing). Fallback when atr column not in DataFrame."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


# ── Swing 检测 ──────────────────────────────────────────────────────────────

def _find_swing_lows(
    low: pd.Series, lookback: int = 60, distance: int = 5
) -> list[float]:
    """检测近 lookback 根 K 线的 swing low 价格列表。"""
    recent = low.iloc[-lookback:].values
    if len(recent) < distance * 2:
        return []
    # find_peaks on negated values finds troughs
    peaks, _ = find_peaks(-recent, distance=distance)
    return [float(recent[p]) for p in peaks]


def _find_swing_highs(
    high: pd.Series, lookback: int = 60, distance: int = 5
) -> list[float]:
    """检测近 lookback 根 K 线的 swing high 价格列表。"""
    recent = high.iloc[-lookback:].values
    if len(recent) < distance * 2:
        return []
    peaks, _ = find_peaks(recent, distance=distance)
    return [float(recent[p]) for p in peaks]


# ── 支撑/阻力提取 ──────────────────────────────────────────────────────────

def _calc_support_levels(df: pd.DataFrame, lookback: int = 60, distance: int = 5) -> dict:
    """从 DataFrame 提取所有候选支撑价位。"""
    last = df.iloc[-1]
    swing_lows = _find_swing_lows(df["low"], lookback=lookback, distance=distance)

    return {
        "ma20": float(last["ma20"]) if pd.notna(last.get("ma20")) else None,
        "ma60": float(last["ma60"]) if pd.notna(last.get("ma60")) else None,
        "boll_lower": float(last["boll_lower"]) if pd.notna(last.get("boll_lower")) else None,
        "swing_low_nearest": float(swing_lows[-1]) if swing_lows else None,
        "swing_low_strongest": float(min(swing_lows)) if swing_lows else None,
    }


def _calc_resistance_levels(df: pd.DataFrame, lookback: int = 60, distance: int = 5) -> dict:
    """从 DataFrame 提取所有候选阻力价位。"""
    last = df.iloc[-1]
    swing_highs = _find_swing_highs(df["high"], lookback=lookback, distance=distance)

    return {
        "boll_upper": float(last["boll_upper"]) if pd.notna(last.get("boll_upper")) else None,
        "swing_high_nearest": float(swing_highs[-1]) if swing_highs else None,
        "swing_high_strongest": float(max(swing_highs)) if swing_highs else None,
    }


# ── 止损计算 ────────────────────────────────────────────────────────────────

def _calc_stop_loss(
    current_price: float,
    atr_value: float,
    support_levels: dict,
    atr_multiplier: float = 2.0,
) -> dict:
    """计算止损价。

    算法：
    1. ATR-based stop = current_price - (atr_value × atr_multiplier)
    2. Support-based stop = 有效支撑位中低于当前价的最高者
    3. Final stop = max(ATR_stop, support_stop) — 取较紧者
    """
    atr_stop = current_price - (atr_value * atr_multiplier)
    # 支撑位止损的最小距离门槛：至少 1×ATR，否则正常波动就会触发
    min_distance = atr_value

    # 找有效支撑位（低于当前价，且距离 >= 1×ATR）
    valid_supports = {
        k: v for k, v in support_levels.items()
        if v is not None and v < current_price and (current_price - v) >= min_distance
    }

    support_stop = None
    support_type = None
    if valid_supports:
        support_type = max(valid_supports, key=valid_supports.get)
        support_stop = valid_supports[support_type]

    # 取较紧者（价格较高的那个）
    if support_stop is not None and support_stop > atr_stop:
        final_stop = support_stop
        method = "support"
    else:
        final_stop = atr_stop
        method = "atr"

    distance_pct = (current_price - final_stop) / current_price

    return {
        "price": round(final_stop, 2),
        "method": method,
        "atr_stop": round(atr_stop, 2),
        "support_stop": round(support_stop, 2) if support_stop else None,
        "support_type": support_type,
        "distance_pct": round(distance_pct, 4),
    }


# ── 止盈计算 ────────────────────────────────────────────────────────────────

def _calc_take_profit(
    current_price: float,
    stop_loss_price: float,
    resistance_levels: dict,
    min_rr_ratio: float = 2.0,
) -> dict:
    """计算止盈价。

    算法：
    1. RR-based target = current_price + risk × min_rr_ratio
    2. Resistance target = 最近有效阻力位（> current_price）
    3. Final = 取两者中较保守（较低）的；若阻力低于 RR 目标则用阻力
    """
    risk = current_price - stop_loss_price
    rr_target = current_price + risk * min_rr_ratio

    # 找有效阻力位（高于当前价）
    valid_resistances = {
        k: v for k, v in resistance_levels.items()
        if v is not None and v > current_price
    }

    resistance_target = None
    resistance_type = None
    if valid_resistances:
        resistance_type = min(valid_resistances, key=valid_resistances.get)
        resistance_target = valid_resistances[resistance_type]

    # 取较保守（较低）的目标
    if resistance_target is not None and resistance_target < rr_target:
        final_tp = resistance_target
        method = "resistance"
    else:
        final_tp = rr_target
        method = "rr_ratio"

    distance_pct = (final_tp - current_price) / current_price

    return {
        "price": round(final_tp, 2),
        "method": method,
        "rr_target": round(rr_target, 2),
        "resistance_target": round(resistance_target, 2) if resistance_target else None,
        "resistance_type": resistance_type,
        "distance_pct": round(distance_pct, 4),
    }


# ── 主入口 ──────────────────────────────────────────────────────────────────

def calculate_tp_sl(
    code: str,
    daily_df: pd.DataFrame,
    atr_period: int = 14,
    atr_multiplier: float = 2.0,
    swing_lookback: int = 60,
    swing_distance: int = 5,
    min_rr_ratio: float = 2.0,
) -> dict:
    """汇总计算止盈/止损/风险回报。

    Parameters
    ----------
    code           : 标的代码
    daily_df       : 已含指标的日线 DataFrame（date 升序）
    atr_period     : ATR 周期（默认 14）
    atr_multiplier : ATR 止损乘数（默认 2.0）
    swing_lookback : swing high/low 回看天数（默认 60）
    swing_distance : 两个 swing 点最小间隔
    min_rr_ratio   : 最低风险回报比（默认 2.0）

    Returns
    -------
    完整 TP/SL 结果字典。
    """
    if daily_df.empty or len(daily_df) < 30:
        return {"data": None, "message": f"{code} 数据不足，需至少 30 根日线"}

    last = daily_df.iloc[-1]
    current_price = float(last["close"])
    date = str(last["date"])

    # ATR: 优先用 DB 列，否则 on-the-fly 计算
    atr_col = f"atr{atr_period}"
    if atr_col in daily_df.columns and pd.notna(last.get(atr_col)):
        atr_value = float(last[atr_col])
    else:
        atr_series = _calc_atr(daily_df["high"], daily_df["low"], daily_df["close"], atr_period)
        atr_value = float(atr_series.iloc[-1])

    # 支撑/阻力
    support_levels = _calc_support_levels(daily_df, lookback=swing_lookback, distance=swing_distance)
    resistance_levels = _calc_resistance_levels(daily_df, lookback=swing_lookback, distance=swing_distance)

    # 止损
    sl_result = _calc_stop_loss(current_price, atr_value, support_levels, atr_multiplier)

    # 止盈
    tp_result = _calc_take_profit(current_price, sl_result["price"], resistance_levels, min_rr_ratio)

    # 盈亏比
    risk_per_share = current_price - sl_result["price"]
    reward_per_share = tp_result["price"] - current_price
    rr_ratio = round(reward_per_share / risk_per_share, 2) if risk_per_share > 0 else 0.0

    # 仓位建议（$10,000 账户 1% 风险）
    risk_1pct = 10000 * 0.01
    suggested_shares = int(risk_1pct / risk_per_share) if risk_per_share > 0 else 0

    return {
        "code": code,
        "current_price": round(current_price, 2),
        "date": date,
        f"atr{atr_period}": round(atr_value, 2),
        "stop_loss": sl_result,
        "take_profit": tp_result,
        "risk_reward_ratio": rr_ratio,
        "risk_per_share": round(risk_per_share, 2),
        "reward_per_share": round(reward_per_share, 2),
        "support_levels": {k: round(v, 2) if v else None for k, v in support_levels.items()},
        "resistance_levels": {k: round(v, 2) if v else None for k, v in resistance_levels.items()},
        "position_sizing": {"risk_1pct_of_10k": suggested_shares},
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
