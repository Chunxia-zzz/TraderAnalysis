"""EMA 交叉信号检测引擎。

检测 EMA5/EMA30 的金叉（空转多）和死叉（多转空），
支持日线和 4H 两个维度。

信号类型：
- EMA_CROSS_BULL_1D / EMA_CROSS_BULL_4H  — 空转多（EMA5 上穿 EMA30）
- EMA_CROSS_BEAR_1D / EMA_CROSS_BEAR_4H  — 多转空（EMA5 下穿 EMA30）
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class EMACrossSignal:
    """EMA 交叉信号。"""
    signal_type: str       # EMA_CROSS_BULL_1D / EMA_CROSS_BEAR_1D / _4H
    strength: float        # 信号强度 0~1
    description: str       # 人类可读描述
    detail: dict = field(default_factory=dict)


def detect_ema_cross(
    df: pd.DataFrame,
    timeframe: str = "1d",
) -> list[EMACrossSignal]:
    """检测最新一根 K 线是否触发 EMA5/EMA30 交叉。

    Parameters
    ----------
    df : 含 ema5, ema30, close 列的 DataFrame（至少 2 根）
    timeframe : "1d" 或 "4h"

    Returns
    -------
    触发的信号列表（0 或 1 个）
    """
    if df is None or len(df) < 2:
        return []

    if "ema5" not in df.columns or "ema30" not in df.columns:
        return []

    prev = df.iloc[-2]
    cur = df.iloc[-1]

    prev_ema5 = prev.get("ema5")
    prev_ema30 = prev.get("ema30")
    cur_ema5 = cur.get("ema5")
    cur_ema30 = cur.get("ema30")

    # 需要所有 EMA 值有效
    if any(pd.isna(v) for v in [prev_ema5, prev_ema30, cur_ema5, cur_ema30]):
        return []

    prev_bull = prev_ema5 >= prev_ema30
    cur_bull = cur_ema5 >= cur_ema30

    suffix = timeframe.upper()  # "1D" or "4H"
    close = cur.get("close", 0)
    date = cur.get("date", "")

    signals = []

    if not prev_bull and cur_bull:
        # 空转多：EMA5 上穿 EMA30
        spread_pct = (cur_ema5 - cur_ema30) / cur_ema30 * 100 if cur_ema30 else 0
        signals.append(EMACrossSignal(
            signal_type=f"EMA_CROSS_BULL_{suffix}",
            strength=min(0.5 + abs(spread_pct) * 0.1, 1.0),
            description=f"{timeframe} EMA5上穿EMA30 (空转多) @ {close:.2f}",
            detail={
                "timeframe": timeframe,
                "date": str(date),
                "close": round(float(close), 2),
                "ema5": round(float(cur_ema5), 2),
                "ema30": round(float(cur_ema30), 2),
                "spread_pct": round(float(spread_pct), 3),
            },
        ))

    elif prev_bull and not cur_bull:
        # 多转空：EMA5 下穿 EMA30
        spread_pct = (cur_ema30 - cur_ema5) / cur_ema30 * 100 if cur_ema30 else 0
        signals.append(EMACrossSignal(
            signal_type=f"EMA_CROSS_BEAR_{suffix}",
            strength=min(0.5 + abs(spread_pct) * 0.1, 1.0),
            description=f"{timeframe} EMA5下穿EMA30 (多转空) @ {close:.2f}",
            detail={
                "timeframe": timeframe,
                "date": str(date),
                "close": round(float(close), 2),
                "ema5": round(float(cur_ema5), 2),
                "ema30": round(float(cur_ema30), 2),
                "spread_pct": round(float(spread_pct), 3),
            },
        ))

    return signals
