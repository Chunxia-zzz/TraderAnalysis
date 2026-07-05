"""技术分析辅助模块：支撑/压力位检测、形态识别、趋势判断。

纯计算层，输入为 storage.query_recent() 返回的 DataFrame，无副作用。
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


# ── 支撑/压力位检测 ────────────────────────────────────────────────────────────


def find_support_resistance(
    df: pd.DataFrame,
    n: int = 2,
    max_levels: int = 5,
) -> tuple[list[dict], list[dict]]:
    """基于 Swing Pivot 聚类检测支撑位和压力位。

    Args:
        df: 含 OHLCV + 指标的 DataFrame（日期升序），至少 20 根。
        n: Pivot 检测的左右窗口大小（默认 2，即前后各2根确认）。
        max_levels: 最多返回的支撑/压力位数量。

    Returns:
        (supports, resistances)，每个元素为 dict:
        {"price": float, "strength": int, "label": str, "type": str}
    """
    if df.empty or len(df) < 10:
        return [], []

    latest = df.iloc[-1]
    close = float(latest["close"])
    atr = float(latest["atr14"]) if pd.notna(latest.get("atr14")) else close * 0.02
    cluster_thresh = atr * 0.6
    price_range = close * 0.25  # 只返回距当前价格 ±25% 以内的位

    highs = df["high"].values
    lows = df["low"].values
    total = len(df)

    # ── 1. 检测 Swing 高/低点 ────────────────────────────────────────────────
    swing_highs: list[tuple[float, int]] = []  # (price, bar_index)
    swing_lows: list[tuple[float, int]] = []

    for i in range(n, total - n):
        h = highs[i]
        l = lows[i]
        if all(h >= highs[i - j] for j in range(1, n + 1)) and \
           all(h >= highs[i + j] for j in range(1, n + 1)):
            swing_highs.append((h, i))
        if all(l <= lows[i - j] for j in range(1, n + 1)) and \
           all(l <= lows[i + j] for j in range(1, n + 1)):
            swing_lows.append((l, i))

    # ── 2. 聚类合并 ───────────────────────────────────────────────────────────
    def cluster_pivots(pivots: list[tuple[float, int]]) -> list[dict]:
        """按价格距离聚类，返回 [{"price", "strength", "recency"}]"""
        if not pivots:
            return []
        # 按价格升序
        pivots_sorted = sorted(pivots, key=lambda x: x[0])
        clusters: list[list[tuple[float, int]]] = [[pivots_sorted[0]]]
        for price, idx in pivots_sorted[1:]:
            if abs(price - clusters[-1][-1][0]) <= cluster_thresh:
                clusters[-1].append((price, idx))
            else:
                clusters.append([(price, idx)])

        result = []
        for cluster in clusters:
            avg_price = sum(p for p, _ in cluster) / len(cluster)
            # 最新的 bar index
            max_idx = max(i for _, i in cluster)
            # 强度 = 命中次数，近期（最近30根内）×2
            recency_bonus = 2 if (total - 1 - max_idx) <= 30 else 1
            strength = len(cluster) * recency_bonus
            result.append({
                "price": avg_price,
                "strength": strength,
                "recency_idx": max_idx,
            })
        return result

    raw_supports = cluster_pivots(swing_lows)
    raw_resistances = cluster_pivots(swing_highs)

    # ── 3. 加入均线动态位 ─────────────────────────────────────────────────────
    ma_levels = [
        ("ma20",  "MA20",  latest.get("ma20")),
        ("ma60",  "MA60",  latest.get("ma60")),
        ("ma120", "MA120", latest.get("ma120")),
        ("ma250", "MA250", latest.get("ma250")),
    ]
    for _col, label, val in ma_levels:
        if val is None or (isinstance(val, float) and math.isnan(val)):
            continue
        price = float(val)
        if abs(price - close) / close > 0.25:
            continue
        entry = {"price": price, "strength": 1, "recency_idx": total - 1, "label": label, "type": "ma"}
        if price < close:
            raw_supports.append(entry)
        else:
            raw_resistances.append(entry)

    # ── 4. 过滤、排序、格式化 ─────────────────────────────────────────────────
    def format_levels(raw: list[dict], is_support: bool) -> list[dict]:
        out = []
        for item in raw:
            price = item["price"]
            # 距离过滤
            if abs(price - close) / close > 0.25:
                continue
            # 方向过滤（支撑在价格下方，压力在价格上方；均线另行处理）
            if item.get("type") != "ma":
                if is_support and price >= close:
                    continue
                if not is_support and price <= close:
                    continue
            strength = item["strength"]
            lbl = item.get("label")
            if lbl is None:
                # swing pivot label
                touch = strength // (2 if (total - 1 - item["recency_idx"]) <= 30 else 1)
                suffix = f"×{touch}" if touch > 1 else ""
                lbl = ("近期低点" if is_support else "近期高点") + suffix
            out.append({
                "price": round(price, 4),
                "strength": strength,
                "label": lbl,
                "type": item.get("type", "swing_low" if is_support else "swing_high"),
            })
        # 按强度降序，相同强度按距离当前价近优先
        out.sort(key=lambda x: (-x["strength"], abs(x["price"] - close)))
        # 去重：价格差 < cluster_thresh 的只保留第一个
        deduped = []
        for item in out:
            if not any(abs(item["price"] - kept["price"]) < cluster_thresh for kept in deduped):
                deduped.append(item)
        return deduped[:max_levels]

    supports = format_levels(raw_supports, is_support=True)
    resistances = format_levels(raw_resistances, is_support=False)

    # 支撑按价格降序（最近支撑在前），压力按价格升序（最近压力在前）
    supports.sort(key=lambda x: -x["price"])
    resistances.sort(key=lambda x: x["price"])

    return supports, resistances


# ── 技术形态检测 ───────────────────────────────────────────────────────────────


def _cross_up(a: pd.Series, b: pd.Series, lookback: int = 5) -> bool:
    """在近 lookback 根内，a 从下方上穿 b。"""
    if len(a) < lookback + 1:
        return False
    for i in range(-lookback, 0):
        if a.iloc[i - 1] < b.iloc[i - 1] and a.iloc[i] >= b.iloc[i]:
            return True
    return False


def _cross_down(a: pd.Series, b: pd.Series, lookback: int = 5) -> bool:
    """在近 lookback 根内，a 从上方下穿 b。"""
    if len(a) < lookback + 1:
        return False
    for i in range(-lookback, 0):
        if a.iloc[i - 1] > b.iloc[i - 1] and a.iloc[i] <= b.iloc[i]:
            return True
    return False


def detect_patterns(df: pd.DataFrame) -> list[dict[str, Any]]:
    """检测技术形态信号，返回命中的信号列表。

    每个信号格式：{"id": str, "label": str, "bullish": bool|None, "desc": str}
    """
    if df.empty or len(df) < 10:
        return []

    last = df.iloc[-1]
    recent5 = df.tail(5)   # noqa: F841（供后续扩展用）
    patterns: list[dict[str, Any]] = []

    def add(id_: str, label: str, bullish: bool | None, desc: str) -> None:
        patterns.append({"id": id_, "label": label, "bullish": bullish, "desc": desc})

    def get(col: str) -> float | None:
        v = last.get(col)
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)

    ma5  = get("ma5");   ma10 = get("ma10")
    ma20 = get("ma20");  ma60 = get("ma60")
    ema5 = get("ema5");  ema10 = get("ema10")
    ema15 = get("ema15"); ema20 = get("ema20")
    dif  = get("dif");   dea  = get("dea")
    rsi12 = get("rsi12")
    close = get("close")
    boll_upper = get("boll_upper"); boll_lower = get("boll_lower")
    vol = get("volume"); vol_ma20 = get("vol_ma20")

    # ── 均线排列 ──────────────────────────────────────────────────────────────
    if all(v is not None for v in [ma5, ma10, ma20, ma60]):
        if ma5 > ma10 > ma20 > ma60:
            add("ma_bull", "均线多头排列", True, "MA5>MA10>MA20>MA60，趋势强势")
        elif ma5 < ma10 < ma20 < ma60:
            add("ma_bear", "均线空头排列", False, "MA5<MA10<MA20<MA60，趋势弱势")

    # ── EMA 飘带 ──────────────────────────────────────────────────────────────
    if all(v is not None for v in [ema5, ema10, ema15, ema20]):
        if ema5 > ema10 > ema15 > ema20:
            add("ema_ribbon_bull", "EMA飘带多头", True, "EMA5>10>15>20，动能向上")
        elif ema5 < ema10 < ema15 < ema20:
            add("ema_ribbon_bear", "EMA飘带空头", False, "EMA5<10<15<20，动能向下")

    # ── MA 金叉/死叉 ──────────────────────────────────────────────────────────
    if "ma5" in df.columns and "ma20" in df.columns:
        tail = df.tail(8)
        if _cross_up(tail["ma5"], tail["ma20"], lookback=6):
            add("golden_cross_fast", "MA5金叉MA20", True, "MA5近期上穿MA20，短期转强")
        elif _cross_down(tail["ma5"], tail["ma20"], lookback=6):
            add("death_cross_fast", "MA5死叉MA20", False, "MA5近期下穿MA20，短期转弱")

    if "ma20" in df.columns and "ma60" in df.columns:
        tail = df.tail(12)
        if _cross_up(tail["ma20"], tail["ma60"], lookback=10):
            add("golden_cross_slow", "MA20金叉MA60", True, "MA20上穿MA60，中期趋势转多")
        elif _cross_down(tail["ma20"], tail["ma60"], lookback=10):
            add("death_cross_slow", "MA20死叉MA60", False, "MA20下穿MA60，中期趋势转空")

    # ── MACD ─────────────────────────────────────────────────────────────────
    if dif is not None and dea is not None:
        if dif > dea:
            add("macd_bull", "MACD金区", True, f"DIF({dif:.3f})>DEA({dea:.3f})，动量偏多")
        else:
            add("macd_bear", "MACD死区", False, f"DIF({dif:.3f})<DEA({dea:.3f})，动量偏空")

        if "dif" in df.columns and "dea" in df.columns:
            tail = df.tail(5)
            if _cross_up(tail["dif"], tail["dea"], lookback=4):
                add("macd_golden", "MACD金叉", True, "DIF近期上穿DEA，短期买入信号")
            elif _cross_down(tail["dif"], tail["dea"], lookback=4):
                add("macd_death", "MACD死叉", False, "DIF近期下穿DEA，短期卖出信号")

    # ── RSI ───────────────────────────────────────────────────────────────────
    if rsi12 is not None:
        if rsi12 > 75:
            add("rsi_overbought", f"RSI超买({rsi12:.1f})", False, "RSI12>75，短期可能回调")
        elif rsi12 < 30:
            add("rsi_oversold", f"RSI超卖({rsi12:.1f})", True, "RSI12<30，短期超卖反弹概率高")

    # ── 布林带 ────────────────────────────────────────────────────────────────
    if close is not None and boll_upper is not None and boll_lower is not None:
        if close > boll_upper:
            add("bb_upper_break", "突破布林上轨", True, "价格突破上轨，强势但注意过热")
        elif close < boll_lower:
            add("bb_lower_break", "跌破布林下轨", False, "价格跌破下轨，弱势但注意超卖")

    # ── 成交量 ────────────────────────────────────────────────────────────────
    if vol is not None and vol_ma20 is not None and vol_ma20 > 0:
        ratio = vol / vol_ma20
        if ratio >= 1.5:
            add("vol_spike", f"放量({ratio:.1f}x均量)", None,
                "成交量显著放大，注意结合价格方向判断")

    return patterns


# ── 趋势判断 ───────────────────────────────────────────────────────────────────


def analyze_trend(df: pd.DataFrame) -> dict[str, Any]:
    """返回多维度趋势判断字典。"""
    if df.empty:
        return {}

    last = df.iloc[-1]

    def get(col: str) -> float | None:
        v = last.get(col)
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)

    close   = get("close") or 0
    ma20    = get("ma20");  ma60  = get("ma60"); ma120 = get("ma120")
    ma5     = get("ma5");   ma10  = get("ma10")
    dif     = get("dif");   dea   = get("dea")
    rsi12   = get("rsi12")
    boll_upper = get("boll_upper"); boll_lower = get("boll_lower"); boll_mid = get("boll_mid")
    vol     = get("volume"); vol_ma20 = get("vol_ma20")
    atr14   = get("atr14")

    # 主趋势：均线多空排列
    primary = "sideways"
    if ma20 and ma60 and ma120:
        if ma20 > ma60 > ma120:
            primary = "up"
        elif ma20 < ma60 < ma120:
            primary = "down"
        elif ma20 > ma60:
            primary = "up"
        elif ma20 < ma60:
            primary = "down"

    # 短期趋势：价格 vs MA5/MA20
    short_term = "sideways"
    if close and ma5 and ma20:
        if close > ma5 and ma5 > ma20:
            short_term = "up"
        elif close < ma5 and ma5 < ma20:
            short_term = "down"
        elif close > ma20:
            short_term = "up"
        elif close < ma20:
            short_term = "down"
    elif close and ma10:
        short_term = "up" if close > ma10 else "down"

    # MACD 偏向
    macd_bias = "neutral"
    if dif is not None and dea is not None:
        if dif > dea:
            macd_bias = "bullish"
        elif dif < dea:
            macd_bias = "bearish"

    # %B 布林带位置
    bb_pct_b: float | None = None
    if boll_upper and boll_lower and (boll_upper - boll_lower) > 0:
        bb_pct_b = round((close - boll_lower) / (boll_upper - boll_lower), 3)

    # 成交量比
    vol_ratio: float | None = None
    if vol and vol_ma20 and vol_ma20 > 0:
        vol_ratio = round(vol / vol_ma20, 2)

    # ATR 百分比
    atr_pct: float | None = None
    if atr14 and close:
        atr_pct = round(atr14 / close, 4)

    return {
        "primary":    primary,
        "short_term": short_term,
        "rsi12":      round(rsi12, 1) if rsi12 else None,
        "macd_bias":  macd_bias,
        "bb_pct_b":   bb_pct_b,
        "vol_ratio":  vol_ratio,
        "atr14":      round(atr14, 4) if atr14 else None,
        "atr_pct":    atr_pct,
    }
