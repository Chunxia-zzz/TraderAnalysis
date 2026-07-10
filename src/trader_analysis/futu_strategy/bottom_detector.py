"""底部信号检测引擎。

纯计算模块：接收已含指标的日线 DataFrame，检测各类见底信号。
与 top_detector.py 对称，不感知持仓状态，不做买入决策。
"""

from __future__ import annotations

import pandas as pd
from scipy.signal import find_peaks

from trader_analysis.futu_strategy import config
from trader_analysis.futu_strategy.top_detector import TopSignal


def detect_all_bottom(daily_df: pd.DataFrame, cfg: dict | None = None) -> list[TopSignal]:
    """对单只标的执行全部底部信号检测，返回当日触发的信号列表。"""
    if cfg is None:
        cfg = config.TOP_DETECTION_CONFIG

    if daily_df.empty or len(daily_df) < 10:
        return []

    detectors = [
        detect_near_low,
        detect_rsi_bottom_divergence,
        detect_macd_bottom_divergence,
        detect_panic_volume,
    ]

    signals = []
    for fn in detectors:
        try:
            sig = fn(daily_df, cfg)
            if sig is not None:
                signals.append(sig)
        except Exception:
            pass

    return signals


def detect_near_low(daily_df: pd.DataFrame, cfg: dict) -> TopSignal | None:
    """信号1：价格接近近期低点（底部支撑区域）。

    与 detect_near_high 对称：当前价距 near_high_lookback 内最低点 5% 以内。
    """
    lookback = cfg.get("near_high_lookback", 120)
    threshold = cfg.get("near_high_threshold", 0.05)

    recent = daily_df.tail(lookback)
    all_time_low = float(recent["low"].min())
    close = float(daily_df.iloc[-1]["close"])

    if all_time_low <= 0 or close <= 0:
        return None

    distance = (close - all_time_low) / all_time_low
    if distance >= threshold:
        return None

    strength = 1.0 - (distance / threshold)
    return TopSignal(
        signal_type="NEAR_LOW",
        strength=round(min(strength, 1.0), 3),
        description=f"价格接近{lookback}日内低点: 距低点{distance*100:.1f}%",
        detail={"all_time_low": all_time_low, "close": close, "distance_pct": round(distance, 4)},
    )


def detect_rsi_bottom_divergence(daily_df: pd.DataFrame, cfg: dict) -> TopSignal | None:
    """信号2：日线 RSI 底背离（价格创新低但 RSI 未创新低）。"""
    lookback = cfg.get("rsi_divergence_lookback", 60)
    period = cfg.get("rsi_divergence_period", 6)
    distance = cfg.get("rsi_divergence_min_distance", 5)
    rsi_col = f"rsi{period}"

    recent = daily_df.tail(lookback).copy().reset_index(drop=True)

    if rsi_col not in recent.columns or recent[rsi_col].isna().all():
        return None
    if "low" not in recent.columns:
        return None

    # 找价格波谷（low 的局部极小值）
    troughs, _ = find_peaks(-recent["low"].values, distance=distance)
    if len(troughs) < 2:
        return None

    idx1, idx2 = troughs[-2], troughs[-1]
    price1 = float(recent["low"].iloc[idx1])
    price2 = float(recent["low"].iloc[idx2])
    rsi1 = float(recent[rsi_col].iloc[idx1])
    rsi2 = float(recent[rsi_col].iloc[idx2])

    # 底背离：价格创新低，但 RSI 未创新低（RSI 更高）
    if not (price2 < price1 and rsi2 > rsi1):
        return None

    strength = (rsi2 - rsi1) / (100 - rsi1) if (100 - rsi1) > 0 else 0.0
    date1 = str(recent["date"].iloc[idx1]) if "date" in recent.columns else ""
    date2 = str(recent["date"].iloc[idx2]) if "date" in recent.columns else ""
    return TopSignal(
        signal_type="RSI_BOTTOM_DIV",
        strength=round(min(strength, 1.0), 3),
        description=f"RSI{period}底背离: 价格新低但RSI从{rsi1:.1f}升至{rsi2:.1f}",
        detail={
            "trough1_date": date1, "trough2_date": date2,
            "price1": round(price1, 2), "price2": round(price2, 2),
            "rsi1": round(rsi1, 1), "rsi2": round(rsi2, 1),
        },
    )


def detect_macd_bottom_divergence(daily_df: pd.DataFrame, cfg: dict) -> TopSignal | None:
    """信号3：日线 MACD 底背离（价格创新低但 MACD 柱线未创新低）。"""
    lookback = cfg.get("macd_divergence_lookback", 60)
    distance = cfg.get("macd_divergence_min_distance", 5)

    recent = daily_df.tail(lookback).copy().reset_index(drop=True)

    if "macd" not in recent.columns or recent["macd"].isna().all():
        return None
    if "low" not in recent.columns:
        return None

    troughs, _ = find_peaks(-recent["low"].values, distance=distance)
    if len(troughs) < 2:
        return None

    idx1, idx2 = troughs[-2], troughs[-1]
    price1 = float(recent["low"].iloc[idx1])
    price2 = float(recent["low"].iloc[idx2])
    macd1 = float(recent["macd"].iloc[idx1])
    macd2 = float(recent["macd"].iloc[idx2])

    # 底背离：价格创新低，但 MACD 未创新低（MACD 柱线更高）
    if not (price2 < price1 and macd2 > macd1):
        return None

    if abs(macd1) < 1e-9:
        strength = 0.5
    else:
        strength = (macd2 - macd1) / abs(macd1)

    date1 = str(recent["date"].iloc[idx1]) if "date" in recent.columns else ""
    date2 = str(recent["date"].iloc[idx2]) if "date" in recent.columns else ""
    return TopSignal(
        signal_type="MACD_BOTTOM_DIV",
        strength=round(min(max(strength, 0.0), 1.0), 3),
        description=f"MACD底背离: 价格新低但MACD从{macd1:.3f}升至{macd2:.3f}",
        detail={
            "trough1_date": date1, "trough2_date": date2,
            "price1": round(price1, 2), "price2": round(price2, 2),
            "macd1": round(macd1, 4), "macd2": round(macd2, 4),
        },
    )


def detect_panic_volume(daily_df: pd.DataFrame, cfg: dict) -> TopSignal | None:
    """信号4：恐慌放量后缩量（底部见底信号）。

    条件：
    1. 近 20 根内峰值成交量 > vol_ma20 × multiplier（恐慌放量）
    2. 峰值后近 3 根均量 < 峰值量 × 0.6（缩量回落）
    """
    multiplier = cfg.get("volume_stall_multiplier", 2.0)
    lookback = 20

    if "vol_ma20" not in daily_df.columns:
        return None

    recent = daily_df.tail(lookback).copy().reset_index(drop=True)
    peak_pos = int(recent["volume"].idxmax())

    vol_ma_val = float(recent["vol_ma20"].iloc[peak_pos]) if not pd.isna(recent["vol_ma20"].iloc[peak_pos]) else 0
    if vol_ma_val <= 0:
        return None

    peak_vol = float(recent["volume"].iloc[peak_pos])
    is_panic = peak_vol > vol_ma_val * multiplier

    after_peak = recent["volume"].iloc[peak_pos:]
    is_shrinking = len(after_peak) >= 3 and float(after_peak.tail(3).mean()) < peak_vol * 0.6

    if not (is_panic and is_shrinking):
        return None

    vol_ratio = peak_vol / vol_ma_val
    strength = min((vol_ratio - multiplier) / multiplier + 0.5, 1.0)
    return TopSignal(
        signal_type="PANIC_VOLUME",
        strength=round(max(strength, 0.0), 3),
        description=f"恐慌放量后缩量: 峰值量比={vol_ratio:.1f}x，已回落",
        detail={"vol_ratio": round(vol_ratio, 2), "peak_pos": peak_pos},
    )
