"""顶部信号检测引擎。

纯计算模块：接收已含指标的日线 DataFrame，检测各类见顶信号。
不感知持仓状态，不做减仓决策（决策逻辑归 sell_advisor.py）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from trader_analysis.futu_strategy import config


@dataclass
class TopSignal:
    """单个顶部信号。"""
    signal_type: str       # 信号类型标识
    strength: float        # 信号强度 0~1
    description: str       # 人类可读描述
    detail: dict = field(default_factory=dict)  # 详细数据（供日志记录）


def detect_all(daily_df: pd.DataFrame, cfg: dict | None = None) -> list[TopSignal]:
    """对单只标的执行全部顶部信号检测，返回当日触发的信号列表。

    Parameters
    ----------
    daily_df : 已含指标的日线 DataFrame（至少 30 根），最后一行为当日
    cfg      : 检测配置，默认使用 config.TOP_DETECTION_CONFIG

    Returns
    -------
    当日触发的 TopSignal 列表（可能为空）
    """
    if cfg is None:
        cfg = config.TOP_DETECTION_CONFIG

    if daily_df.empty or len(daily_df) < 10:
        return []

    detectors = [
        detect_near_high,
        detect_volume_stall,
        detect_rsi_top_divergence,
        detect_macd_top_divergence,
        detect_upper_shadow,
        detect_boll_squeeze,
        detect_acceleration,
        detect_break_ma5,
        detect_ma5_death_cross,
        detect_ma5_no_recovery,
        detect_emergency_stop,
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


def detect_near_high(daily_df: pd.DataFrame, cfg: dict) -> TopSignal | None:
    """信号1：价格接近前高（近 near_high_lookback 根内的最高点）。

    strength = 1 - (distance / threshold)，越接近越强。
    """
    lookback = cfg.get("near_high_lookback", 120)
    threshold = cfg.get("near_high_threshold", 0.05)

    recent = daily_df.tail(lookback)
    all_time_high = float(recent["high"].max())
    close = float(daily_df.iloc[-1]["close"])

    if all_time_high <= 0 or close <= 0:
        return None

    distance = (all_time_high - close) / all_time_high
    if distance >= threshold:
        return None

    strength = 1.0 - (distance / threshold)
    return TopSignal(
        signal_type="NEAR_HIGH",
        strength=round(min(strength, 1.0), 3),
        description=f"价格接近{lookback}日内前高: 距前高{distance*100:.1f}%",
        detail={"all_time_high": all_time_high, "close": close, "distance_pct": round(distance, 4)},
    )


def detect_volume_stall(daily_df: pd.DataFrame, cfg: dict) -> TopSignal | None:
    """信号2：天量滞涨（放出巨量但价格基本不动）。"""
    multiplier = cfg.get("volume_stall_multiplier", 2.0)
    max_change = cfg.get("volume_stall_max_change", 0.02)

    last = daily_df.iloc[-1]
    vol = float(last.get("volume") or 0)
    vol_ma = float(last.get("vol_ma20") or 0)
    close = float(last.get("close") or 0)
    open_ = float(last.get("open") or 0)

    if vol_ma <= 0 or open_ <= 0:
        return None

    is_heavy_vol = vol > vol_ma * multiplier
    price_change = abs(close - open_) / open_
    is_stall = price_change < max_change

    if not (is_heavy_vol and is_stall):
        return None

    vol_ratio = vol / vol_ma
    strength = min(vol_ratio / (multiplier * 2), 1.0)
    return TopSignal(
        signal_type="VOLUME_STALL",
        strength=round(strength, 3),
        description=f"天量滞涨: 量比={vol_ratio:.1f}x, 涨跌幅={price_change*100:.2f}%",
        detail={"vol_ratio": round(vol_ratio, 2), "price_change_pct": round(price_change, 4)},
    )


def detect_rsi_top_divergence(daily_df: pd.DataFrame, cfg: dict) -> TopSignal | None:
    """信号3：日线 RSI 顶背离（价格创新高但 RSI 走低）。"""
    lookback = cfg.get("rsi_divergence_lookback", 60)
    period = cfg.get("rsi_divergence_period", 6)
    distance = cfg.get("rsi_divergence_min_distance", 5)
    rsi_col = f"rsi{period}"

    recent = daily_df.tail(lookback).copy().reset_index(drop=True)

    if rsi_col not in recent.columns or recent[rsi_col].isna().all():
        return None
    if "high" not in recent.columns:
        return None

    peaks, _ = find_peaks(recent["high"].values, distance=distance)
    if len(peaks) < 2:
        return None

    idx1, idx2 = peaks[-2], peaks[-1]
    price1 = float(recent["high"].iloc[idx1])
    price2 = float(recent["high"].iloc[idx2])
    rsi1 = float(recent[rsi_col].iloc[idx1])
    rsi2 = float(recent[rsi_col].iloc[idx2])

    if not (price2 >= price1 and rsi2 < rsi1):
        return None

    strength = (rsi1 - rsi2) / rsi1 if rsi1 > 0 else 0.0
    date1 = str(recent["date"].iloc[idx1]) if "date" in recent.columns else ""
    date2 = str(recent["date"].iloc[idx2]) if "date" in recent.columns else ""
    return TopSignal(
        signal_type="RSI_TOP_DIV",
        strength=round(min(strength, 1.0), 3),
        description=f"RSI{period}顶背离: 价格新高但RSI从{rsi1:.1f}降至{rsi2:.1f}",
        detail={
            "peak1_date": date1, "peak2_date": date2,
            "price1": round(price1, 2), "price2": round(price2, 2),
            "rsi1": round(rsi1, 1), "rsi2": round(rsi2, 1),
        },
    )


def detect_macd_top_divergence(daily_df: pd.DataFrame, cfg: dict) -> TopSignal | None:
    """信号4：日线 MACD 顶背离（价格创新高但 MACD 柱线走低）。"""
    lookback = cfg.get("macd_divergence_lookback", 60)
    distance = cfg.get("macd_divergence_min_distance", 5)

    recent = daily_df.tail(lookback).copy().reset_index(drop=True)

    if "macd" not in recent.columns or recent["macd"].isna().all():
        return None
    if "high" not in recent.columns:
        return None

    peaks, _ = find_peaks(recent["high"].values, distance=distance)
    if len(peaks) < 2:
        return None

    idx1, idx2 = peaks[-2], peaks[-1]
    price1 = float(recent["high"].iloc[idx1])
    price2 = float(recent["high"].iloc[idx2])
    macd1 = float(recent["macd"].iloc[idx1])
    macd2 = float(recent["macd"].iloc[idx2])

    if not (price2 >= price1 and macd2 < macd1):
        return None

    if abs(macd1) < 1e-9:
        strength = 0.5
    else:
        strength = (macd1 - macd2) / abs(macd1)

    date1 = str(recent["date"].iloc[idx1]) if "date" in recent.columns else ""
    date2 = str(recent["date"].iloc[idx2]) if "date" in recent.columns else ""
    return TopSignal(
        signal_type="MACD_TOP_DIV",
        strength=round(min(max(strength, 0.0), 1.0), 3),
        description=f"MACD顶背离: 价格新高但MACD从{macd1:.3f}降至{macd2:.3f}",
        detail={
            "peak1_date": date1, "peak2_date": date2,
            "price1": round(price1, 2), "price2": round(price2, 2),
            "macd1": round(macd1, 4), "macd2": round(macd2, 4),
        },
    )


def detect_upper_shadow(daily_df: pd.DataFrame, cfg: dict) -> TopSignal | None:
    """信号5：连续长上影线（阴线/阳线上方出现长影线）。"""
    shadow_ratio_threshold = cfg.get("upper_shadow_ratio", 0.6)
    consecutive = cfg.get("upper_shadow_consecutive", 2)

    # 取最近 consecutive+1 根（容忍1根不满足）
    n = consecutive + 1
    if len(daily_df) < n:
        return None

    recent = daily_df.tail(n)
    ratios = []
    for _, row in recent.iterrows():
        high = float(row.get("high") or 0)
        low = float(row.get("low") or 0)
        open_ = float(row.get("open") or 0)
        close = float(row.get("close") or 0)
        body_top = max(open_, close)
        total_range = high - low
        if total_range < 1e-9:
            ratios.append(0.0)
            continue
        upper_shadow = high - body_top
        ratios.append(upper_shadow / total_range)

    qualified = sum(1 for r in ratios if r > shadow_ratio_threshold)
    if qualified < consecutive:
        return None

    avg_ratio = float(np.mean(ratios))
    return TopSignal(
        signal_type="UPPER_SHADOW",
        strength=round(min(avg_ratio / 1.0, 1.0), 3),
        description=f"连续{consecutive}根长上影线: 平均上影比={avg_ratio*100:.1f}%",
        detail={"ratios": [round(r, 3) for r in ratios], "qualified_count": qualified},
    )


def detect_boll_squeeze(daily_df: pd.DataFrame, cfg: dict) -> TopSignal | None:
    """信号6：布林带上轨走平/收口（高位动能衰竭）。

    前提：当前价格在布林带上半区（%B > 0.5）。
    """
    lookback = cfg.get("boll_squeeze_lookback", 10)
    threshold = cfg.get("boll_squeeze_threshold", -0.2)

    if len(daily_df) < lookback + 1:
        return None

    last = daily_df.iloc[-1]
    upper = float(last.get("boll_upper") or 0)
    lower = float(last.get("boll_lower") or 0)
    mid = float(last.get("boll_mid") or 0)
    close = float(last.get("close") or 0)

    if upper <= lower or mid <= 0:
        return None

    pct_b = (close - lower) / (upper - lower)
    if pct_b <= 0.7:
        return None

    # 计算 lookback 期间带宽变化率
    bw_now = (upper - lower) / mid

    old = daily_df.iloc[-(lookback + 1)]
    old_upper = float(old.get("boll_upper") or 0)
    old_lower = float(old.get("boll_lower") or 0)
    old_mid = float(old.get("boll_mid") or 0)

    if old_upper <= old_lower or old_mid <= 0:
        return None

    bw_old = (old_upper - old_lower) / old_mid
    if bw_old < 1e-9:
        return None

    change_rate = (bw_now - bw_old) / bw_old
    if change_rate >= threshold:
        return None

    strength = abs(change_rate) / abs(threshold)
    return TopSignal(
        signal_type="BOLL_SQUEEZE",
        strength=round(min(strength, 1.0), 3),
        description=f"布林带高位收口: 带宽变化{change_rate*100:.1f}%, %B={pct_b:.2f}",
        detail={"bw_change_rate": round(change_rate, 4), "pct_b": round(pct_b, 3)},
    )


def detect_acceleration(daily_df: pd.DataFrame, cfg: dict) -> TopSignal | None:
    """信号7：加速赶顶（近期涨速远超中期均速）。"""
    short_w = cfg.get("acceleration_short_window", 5)
    long_w = cfg.get("acceleration_long_window", 20)
    acc_ratio = cfg.get("acceleration_ratio", 2.5)

    if len(daily_df) < long_w + 1:
        return None

    closes = daily_df["close"].values
    close_now = float(closes[-1])
    close_short = float(closes[-(short_w + 1)])
    close_long = float(closes[-(long_w + 1)])

    if close_short <= 0 or close_long <= 0:
        return None

    short_slope = (close_now - close_short) / close_short / short_w
    long_slope = (close_now - close_long) / close_long / long_w

    if long_slope <= 0:
        return None

    ratio = short_slope / long_slope
    if ratio <= acc_ratio:
        return None

    strength = min(ratio / acc_ratio, 2.0) / 2.0
    return TopSignal(
        signal_type="ACCELERATION",
        strength=round(strength, 3),
        description=f"加速赶顶: 短期斜率/长期斜率={ratio:.1f}x",
        detail={"short_slope": round(short_slope, 5), "long_slope": round(long_slope, 5), "ratio": round(ratio, 2)},
    )


def detect_break_ma5(daily_df: pd.DataFrame, cfg: dict) -> TopSignal | None:
    """减仓确认信号A：收盘刚跌破 MA5（当日跌破，前日未跌破）。"""
    if len(daily_df) < 2:
        return None

    last = daily_df.iloc[-1]
    prev = daily_df.iloc[-2]

    close_now = float(last.get("close") or 0)
    ma5_now = float(last.get("ma5") or 0)
    close_prev = float(prev.get("close") or 0)
    ma5_prev = float(prev.get("ma5") or 0)

    if ma5_now <= 0 or ma5_prev <= 0:
        return None

    just_broke = close_now < ma5_now and close_prev >= ma5_prev
    if not just_broke:
        return None

    strength = (ma5_now - close_now) / ma5_now
    return TopSignal(
        signal_type="BREAK_MA5",
        strength=round(min(strength, 1.0), 3),
        description=f"收盘跌破MA5: close={close_now:.2f} < ma5={ma5_now:.2f}",
        detail={"close": round(close_now, 2), "ma5": round(ma5_now, 2)},
    )


def detect_ma5_death_cross(daily_df: pd.DataFrame, cfg: dict) -> TopSignal | None:
    """减仓确认信号B：MA5 刚下穿 MA10（死叉）。"""
    if len(daily_df) < 2:
        return None

    last = daily_df.iloc[-1]
    prev = daily_df.iloc[-2]

    ma5_now = float(last.get("ma5") or 0)
    ma10_now = float(last.get("ma10") or 0)
    ma5_prev = float(prev.get("ma5") or 0)
    ma10_prev = float(prev.get("ma10") or 0)

    if ma5_now <= 0 or ma10_now <= 0 or ma5_prev <= 0 or ma10_prev <= 0:
        return None

    just_crossed = ma5_now < ma10_now and ma5_prev >= ma10_prev
    if not just_crossed:
        return None

    strength = (ma10_now - ma5_now) / ma10_now
    return TopSignal(
        signal_type="MA5_DEATH_CROSS",
        strength=round(min(strength, 1.0), 3),
        description=f"MA5死叉MA10: ma5={ma5_now:.2f} < ma10={ma10_now:.2f}",
        detail={"ma5": round(ma5_now, 2), "ma10": round(ma10_now, 2)},
    )


def detect_ma5_no_recovery(daily_df: pd.DataFrame, cfg: dict) -> TopSignal | None:
    """减仓确认信号C：连续 N 日收盘均低于 MA5（无力回升）。"""
    recovery_days = cfg.get("ma5_recovery_days", 2)

    if len(daily_df) < recovery_days:
        return None

    recent = daily_df.tail(recovery_days)
    all_below = all(
        float(row.get("close") or 0) < float(row.get("ma5") or float("inf"))
        for _, row in recent.iterrows()
        if float(row.get("ma5") or 0) > 0
    )

    if not all_below:
        return None

    last = daily_df.iloc[-1]
    close = float(last.get("close") or 0)
    ma5 = float(last.get("ma5") or 0)
    return TopSignal(
        signal_type="MA5_NO_RECOVERY",
        strength=1.0,
        description=f"连续{recovery_days}日未站回MA5: close={close:.2f} ma5={ma5:.2f}",
        detail={"consecutive_days": recovery_days, "close": round(close, 2), "ma5": round(ma5, 2)},
    )


def detect_emergency_stop(daily_df: pd.DataFrame, cfg: dict) -> TopSignal | None:
    """紧急止损信号：单日暴跌 > emergency_drop_pct 或跌破 MA20。"""
    drop_pct = cfg.get("emergency_drop_pct", 0.07)
    ma_period = cfg.get("emergency_ma_period", 20)

    if len(daily_df) < 2:
        return None

    last = daily_df.iloc[-1]
    prev = daily_df.iloc[-2]

    close_now = float(last.get("close") or 0)
    close_prev = float(prev.get("close") or 0)

    if close_prev > 0:
        day_change = (close_now - close_prev) / close_prev
        if day_change < -drop_pct:
            return TopSignal(
                signal_type="EMERGENCY_STOP",
                strength=1.0,
                description=f"单日暴跌{day_change*100:.1f}%，触发紧急止损",
                detail={"day_change": round(day_change, 4), "trigger": "drop"},
            )

    ma_col = f"ma{ma_period}"
    ma_now = float(last.get(ma_col) or 0)
    ma_prev = float(prev.get(ma_col) or 0)

    if ma_now > 0 and ma_prev > 0:
        just_broke_ma = close_now < ma_now and close_prev >= ma_prev
        if just_broke_ma:
            return TopSignal(
                signal_type="EMERGENCY_STOP",
                strength=1.0,
                description=f"跌破MA{ma_period}({ma_now:.2f})，触发紧急止损",
                detail={"ma_value": round(ma_now, 2), "close": round(close_now, 2), "trigger": f"ma{ma_period}"},
            )

    return None
