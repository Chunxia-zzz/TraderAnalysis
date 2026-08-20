"""底部支撑信号检测引擎。

纯计算模块：接收已含指标的日线 DataFrame，检测各类底部支撑信号。
不感知持仓状态，不做建仓决策。

信号类型（7 个）：
1. NEAR_SUPPORT  — 价格在关键均线支撑附近
2. DEEP_V        — 日内跌破支撑均线但收回，收长下影线
3. VOLUME_SHRINK — 连续缩量（卖压衰竭）
4. RSI_BOTTOM_DIV— 日线 RSI 底背离
5. W_BOTTOM      — W底/双底形态
6. SUPPORT_CONFIRM— 前日触底后今日确认反弹
7. RECLAIM_MA5   — 重新站上 MA5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd
from scipy.signal import find_peaks

from trader_analysis.futu_strategy import config

logger = logging.getLogger(__name__)


@dataclass
class BottomSignal:
    """单个底部信号。"""
    signal_type: str       # 信号类型标识
    strength: float        # 信号强度 0~1
    description: str       # 人类可读描述
    detail: dict = field(default_factory=dict)  # 详细数据


def detect_all(daily_df: pd.DataFrame, cfg: dict | None = None) -> list[BottomSignal]:
    """对单只标的执行全部底部信号检测，返回当日触发的信号列表。

    Parameters
    ----------
    daily_df : 已含指标的日线 DataFrame（至少 120 根），最后一行为当日
    cfg      : 检测配置，默认使用 config.BOTTOM_DETECTION_CONFIG

    Returns
    -------
    当日触发的 BottomSignal 列表（可能为空）
    """
    if cfg is None:
        cfg = config.BOTTOM_DETECTION_CONFIG

    if daily_df.empty or len(daily_df) < 30:
        return []

    detectors = [
        detect_near_support,
        detect_deep_v,
        detect_volume_shrink,
        detect_rsi_bottom_divergence,
        detect_w_bottom,
        detect_support_confirm,
        detect_reclaim_ma5,
        detect_rsi_cross_50,
        detect_boll_squeeze_break,
        detect_gap_up,
    ]

    signals = []
    for fn in detectors:
        try:
            sig = fn(daily_df, cfg)
            if sig is not None:
                signals.append(sig)
        except Exception as exc:
            logger.warning("底部检测器 %s 异常: %s", getattr(fn, "__name__", fn), exc)

    return signals


def detect_near_support(daily_df: pd.DataFrame, cfg: dict) -> BottomSignal | None:
    """信号1：价格在关键均线支撑附近。

    遍历 support_ma_periods 中每根均线，找距离最近的支撑。
    距离 < near_support_threshold 且价格在均线附近（上方或略微下方）→ 触发。
    """
    last = daily_df.iloc[-1]
    close = float(last["close"])
    threshold = cfg.get("near_support_threshold", 0.02)
    ma_periods = cfg.get("support_ma_periods", [20, 30, 50, 60])

    best_ma = None
    best_distance = float("inf")
    best_ma_value = 0.0

    for period in ma_periods:
        ma_col = f"ma{period}"
        if ma_col not in daily_df.columns:
            continue
        ma_val = float(last.get(ma_col) or 0)
        if ma_val <= 0:
            continue

        distance = (close - ma_val) / ma_val  # 正=在上方，负=在下方
        abs_distance = abs(distance)

        if abs_distance < threshold and abs_distance < best_distance:
            best_distance = abs_distance
            best_ma = ma_col
            best_ma_value = ma_val

    if best_ma is None:
        return None

    strength = 1.0 - (best_distance / threshold)
    return BottomSignal(
        signal_type="NEAR_SUPPORT",
        strength=round(min(strength, 1.0), 3),
        description=f"价格接近{best_ma}支撑({best_ma_value:.2f})，距离{best_distance*100:.1f}%",
        detail={
            "support_ma": best_ma,
            "support_price": round(best_ma_value, 2),
            "distance_pct": round(best_distance, 4),
            "close": round(close, 2),
        },
    )


def detect_deep_v(daily_df: pd.DataFrame, cfg: dict) -> BottomSignal | None:
    """信号2：深V — 日内跌破支撑均线但收回，收长下影线。

    条件（不依赖距离门槛，适合高波动动量资产）：
    1. low < MA（盘中跌破）
    2. close > MA（收盘站回）
    3. abs(close - low) > abs(high - close)（下影线 > 上部分）

    从所有被打穿又站回的均线中，选最高的那根（最强支撑测试）。
    """
    last = daily_df.iloc[-1]
    close = float(last["close"])
    low = float(last["low"])
    high = float(last["high"])
    ma_periods = cfg.get("support_ma_periods", [20, 30, 50, 60])

    # 下影线必须主导
    lower_shadow_dominant = abs(close - low) > abs(high - close)
    if not lower_shadow_dominant:
        return None

    # 找所有满足 low < MA < close 的均线，取最高的（最强支撑）
    support_ma = None
    support_price = 0.0
    for period in ma_periods:
        ma_col = f"ma{period}"
        if ma_col not in daily_df.columns:
            continue
        ma_val = float(last.get(ma_col) or 0)
        if ma_val <= 0:
            continue
        if low < ma_val < close:
            # 盘中跌破且收盘站回，取最高的MA
            if ma_val > support_price:
                support_ma = ma_col
                support_price = ma_val

    if support_ma is None:
        return None

    total_range = high - low
    shadow_ratio = abs(close - low) / total_range if total_range > 0 else 0
    return BottomSignal(
        signal_type="DEEP_V",
        strength=round(min(shadow_ratio, 1.0), 3),
        description=f"深V确认: 跌破{support_ma}({support_price:.2f})后收回，下影线占比{shadow_ratio*100:.0f}%",
        detail={
            "support_ma": support_ma,
            "support_price": round(support_price, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "high": round(high, 2),
            "shadow_ratio": round(shadow_ratio, 3),
        },
    )


def detect_volume_shrink(daily_df: pd.DataFrame, cfg: dict) -> BottomSignal | None:
    """信号3：连续缩量（卖压衰竭）。

    条件：最近 N 日每日 volume < vol_ma20 × shrink_ratio。
    """
    shrink_ratio = cfg.get("volume_shrink_ratio", 0.7)
    shrink_days = cfg.get("volume_shrink_days", 3)

    if len(daily_df) < shrink_days:
        return None
    if "vol_ma20" not in daily_df.columns:
        return None

    recent = daily_df.tail(shrink_days)
    vol_ma_last = float(daily_df.iloc[-1].get("vol_ma20") or 0)
    if vol_ma_last <= 0:
        return None

    threshold_vol = vol_ma_last * shrink_ratio
    all_shrink = all(float(row.get("volume") or 0) < threshold_vol for _, row in recent.iterrows())

    if not all_shrink:
        return None

    avg_vol = float(recent["volume"].mean())
    ratio = avg_vol / vol_ma_last
    strength = 1.0 - ratio  # 缩量程度
    return BottomSignal(
        signal_type="VOLUME_SHRINK",
        strength=round(max(min(strength, 1.0), 0.0), 3),
        description=f"连续{shrink_days}日缩量: 均量/MA20={ratio:.2f}",
        detail={
            "shrink_days": shrink_days,
            "avg_volume": round(avg_vol, 0),
            "vol_ma20": round(vol_ma_last, 0),
            "ratio": round(ratio, 3),
        },
    )


def detect_rsi_bottom_divergence(daily_df: pd.DataFrame, cfg: dict) -> BottomSignal | None:
    """信号4：日线 RSI 底背离（价格创新低但 RSI 未创新低）。"""
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

    # 底背离：价格创新低或持平，但 RSI 走高
    if not (price2 <= price1 and rsi2 > rsi1):
        return None

    strength = (rsi2 - rsi1) / rsi2 if rsi2 > 0 else 0.0
    date1 = str(recent["date"].iloc[idx1]) if "date" in recent.columns else ""
    date2 = str(recent["date"].iloc[idx2]) if "date" in recent.columns else ""
    return BottomSignal(
        signal_type="RSI_BOTTOM_DIV",
        strength=round(min(strength, 1.0), 3),
        description=f"RSI{period}底背离: 价格新低但RSI从{rsi1:.1f}升至{rsi2:.1f}",
        detail={
            "trough1_date": date1, "trough2_date": date2,
            "price1": round(price1, 2), "price2": round(price2, 2),
            "rsi1": round(rsi1, 1), "rsi2": round(rsi2, 1),
        },
    )


def detect_w_bottom(daily_df: pd.DataFrame, cfg: dict) -> BottomSignal | None:
    """信号5：W底/双底形态。

    条件：
    1. 最近 lookback 根内找两个波谷
    2. 两底价差 < tolerance（平行底或略高底）
    3. 两底之间有反弹高点（颈线）
    4. 当前价在第二个底附近或已开始反弹
    """
    lookback = cfg.get("w_bottom_lookback", 30)
    tolerance = cfg.get("w_bottom_price_tolerance", 0.03)

    recent = daily_df.tail(lookback).copy().reset_index(drop=True)
    if len(recent) < 10:
        return None

    # 找两个谷
    troughs, _ = find_peaks(-recent["low"].values, distance=5)
    if len(troughs) < 2:
        return None

    idx1, idx2 = troughs[-2], troughs[-1]
    low1 = float(recent["low"].iloc[idx1])
    low2 = float(recent["low"].iloc[idx2])

    if low1 <= 0:
        return None

    # 两底价差在容忍度内
    price_diff = abs(low2 - low1) / low1
    if price_diff > tolerance:
        return None

    # 两底之间有反弹（颈线）
    between = recent.iloc[idx1:idx2 + 1]
    neckline = float(between["high"].max())
    if neckline <= max(low1, low2) * 1.02:
        return None

    # 当前在第二个底附近或已开始反弹
    current_close = float(recent["close"].iloc[-1])
    is_near_bottom2 = current_close <= low2 * (1 + tolerance)
    is_bouncing = current_close > low2

    if not (is_near_bottom2 or is_bouncing):
        return None

    strength = 1.0 - price_diff / tolerance  # 两底越接近越强
    date1 = str(recent["date"].iloc[idx1]) if "date" in recent.columns else ""
    date2 = str(recent["date"].iloc[idx2]) if "date" in recent.columns else ""
    return BottomSignal(
        signal_type="W_BOTTOM",
        strength=round(min(max(strength, 0.0), 1.0), 3),
        description=f"W底形态: 底1={low1:.2f}, 底2={low2:.2f}, 颈线={neckline:.2f}",
        detail={
            "low1": round(low1, 2),
            "low2": round(low2, 2),
            "neckline": round(neckline, 2),
            "trough1_date": date1,
            "trough2_date": date2,
            "price_diff_pct": round(price_diff, 4),
        },
    )


def detect_support_confirm(daily_df: pd.DataFrame, cfg: dict) -> BottomSignal | None:
    """信号6：支撑确认 — 前日触底后，今日收盘高于前日收盘。

    简化判断前日形态：前日 low < 前日 ma_support 且 前日 close > 前日 ma_support
    （即前日有深V特征），今日 close > 前日 close。
    """
    if len(daily_df) < 2:
        return None

    last = daily_df.iloc[-1]
    prev = daily_df.iloc[-2]
    threshold = cfg.get("near_support_threshold", 0.02)
    ma_periods = cfg.get("support_ma_periods", [20, 30, 50, 60])

    today_close = float(last["close"])
    prev_close = float(prev["close"])
    prev_low = float(prev["low"])

    # 检查前日是否有深V特征（跌破某支撑均线后收回）
    prev_had_deep_v = False
    for period in ma_periods:
        ma_col = f"ma{period}"
        if ma_col not in daily_df.columns:
            continue
        prev_ma = float(prev.get(ma_col) or 0)
        if prev_ma <= 0:
            continue
        if prev_low < prev_ma and prev_close > prev_ma:
            prev_had_deep_v = True
            break

    if not prev_had_deep_v:
        return None

    # 今日收盘高于前日收盘
    if today_close <= prev_close:
        return None

    gain = (today_close - prev_close) / prev_close
    return BottomSignal(
        signal_type="SUPPORT_CONFIRM",
        strength=round(min(gain * 10, 1.0), 3),  # 涨1%=0.1, 涨10%=1.0
        description=f"支撑确认: 前日深V后今日上涨{gain*100:.1f}%",
        detail={
            "prev_close": round(prev_close, 2),
            "today_close": round(today_close, 2),
            "gain_pct": round(gain, 4),
        },
    )


def detect_reclaim_ma5(daily_df: pd.DataFrame, cfg: dict) -> BottomSignal | None:
    """信号7：重新站上 MA5。

    条件：当日 close > ma5 且前日 close <= ma5（刚站上）。
    """
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

    # 刚站上 MA5
    just_reclaimed = close_now > ma5_now and close_prev <= ma5_prev
    if not just_reclaimed:
        return None

    strength = (close_now - ma5_now) / ma5_now
    return BottomSignal(
        signal_type="RECLAIM_MA5",
        strength=round(min(strength * 10, 1.0), 3),
        description=f"重新站上MA5: close={close_now:.2f} > ma5={ma5_now:.2f}",
        detail={"close": round(close_now, 2), "ma5": round(ma5_now, 2)},
    )


def detect_rsi_cross_50(daily_df: pd.DataFrame, cfg: dict) -> BottomSignal | None:
    """信号8：RSI6 从 50 下方上穿 50 中轴，动量由弱转强。"""
    period = cfg.get("rsi_divergence_period", 6)
    rsi_col = f"rsi{period}"

    if rsi_col not in daily_df.columns or len(daily_df) < 2:
        return None

    prev_rsi = float(daily_df.iloc[-2].get(rsi_col) or 0)
    last_rsi = float(daily_df.iloc[-1].get(rsi_col) or 0)

    if prev_rsi <= 0 or last_rsi <= 0:
        return None

    # 刚上穿 50 中轴
    if not (prev_rsi < 50 <= last_rsi):
        return None

    strength = min((last_rsi - 50) / 20, 1.0)  # 50→0，70→1
    return BottomSignal(
        signal_type="RSI_CROSS_50",
        strength=round(strength, 3),
        description=f"RSI{period}上穿50中轴: {prev_rsi:.1f}→{last_rsi:.1f}",
        detail={"prev_rsi": round(prev_rsi, 1), "last_rsi": round(last_rsi, 1)},
    )


def detect_boll_squeeze_break(daily_df: pd.DataFrame, cfg: dict) -> BottomSignal | None:
    """信号9：布林带收窄后放量突破中轨，见底启动。

    条件：
    1. 当前布林带宽处于近 lookback 日低位（< 30% 分位）
    2. 收盘价站上中轨
    3. 成交量放大（> vol_ma20 × 1.5）
    """
    lookback = cfg.get("boll_squeeze_break_lookback", 60)

    if len(daily_df) < 20:
        return None
    for col in ("boll_upper", "boll_lower", "boll_mid"):
        if col not in daily_df.columns:
            return None

    recent = daily_df.tail(lookback)
    last = daily_df.iloc[-1]
    upper = float(last.get("boll_upper") or 0)
    lower = float(last.get("boll_lower") or 0)
    mid = float(last.get("boll_mid") or 0)
    if upper <= lower or mid <= 0:
        return None

    bw_now = (upper - lower) / mid
    bw_series = (recent["boll_upper"] - recent["boll_lower"]) / recent["boll_mid"]
    bw_series = bw_series.dropna()
    if len(bw_series) < 20:
        return None

    # 当前带宽处于历史低位（< 30% 分位 = 收窄）
    pct = float((bw_series < bw_now).sum()) / len(bw_series)
    if pct > 0.3:
        return None

    # 放量突破中轨
    close = float(last.get("close") or 0)
    vol = float(last.get("volume") or 0)
    vol_ma = float(last.get("vol_ma20") or 0)
    if close <= mid or vol_ma <= 0:
        return None
    if vol < vol_ma * 1.5:
        return None

    strength = min(1.0 - pct * 3, 1.0)  # 收得越窄越强
    return BottomSignal(
        signal_type="BOLL_SQUEEZE_BREAK",
        strength=round(strength, 3),
        description=f"布林收口突破: 带宽分位{pct*100:.0f}%, 放量突破中轨",
        detail={"bw_pct": round(pct, 3), "vol_ratio": round(vol / vol_ma, 2)},
    )


def detect_gap_up(daily_df: pd.DataFrame, cfg: dict) -> BottomSignal | None:
    """信号10：向上跳空缺口，今日开盘价 > 昨日最高价。"""
    gap_threshold = cfg.get("gap_threshold", 0.01)

    if len(daily_df) < 2:
        return None

    today_open = float(daily_df.iloc[-1].get("open") or 0)
    prev_high = float(daily_df.iloc[-2].get("high") or 0)
    if today_open <= 0 or prev_high <= 0:
        return None

    gap = (today_open - prev_high) / prev_high
    if gap < gap_threshold:
        return None

    strength = min(gap / 0.05, 1.0)  # 1%→0.2，5%→1
    return BottomSignal(
        signal_type="GAP_UP",
        strength=round(strength, 3),
        description=f"向上跳空缺口: 开盘{today_open:.2f} > 昨高{prev_high:.2f} (缺口{gap*100:.1f}%)",
        detail={"gap_pct": round(gap, 4)},
    )
