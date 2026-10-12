"""利弗莫尔（Livermore）关键点信号引擎。

与 ``scorer.py`` 的均值回归体系**完全独立**
------------------------------------------
- 均值回归：越跌（超卖）→ 分数越高 → 买跌
- 利弗莫尔：突破关键点 → 才是买点 → 买涨

两者方向相反，因此本模块：

1. **绝不并入 ``total_score``**（混在一起会互相抵消）；
2. **不写入 ``top_signal_log`` / ``bottom_signal_log``**（那两张表的语义是顶/底背离）；
3. 独立写入 ``livermore_signal_log``，由 ``/api/livermore/*`` 暴露给前端。

概念映射（《股票大作手回忆录》→ 工程实现）
------------------------------------------
====================  ==========================================================
利弗莫尔要素           实现
====================  ==========================================================
关键点 Pivotal Point   整理平台（窄幅箱体）的上沿。突破上沿 = 买点
反转关键点             平台建立时中期趋势尚未转多（日线 MA20 ≤ MA60）→ 突破是反转
连续关键点             平台建立时中期趋势已向上（日线 MA20 > MA60）→ 突破是加仓点
量能确认               突破当日 ``volume / vol_ma20 ≥ VOL_CONFIRM_RATIO``
顺势                   周线潮汐（周线快慢均线）必须向上才给做多突破信号
龙头                   相对强度 ``RS = 个股 60 日涨幅 − SPY 60 日涨幅``
跌破关键点即离场        收盘价 < 关键点 − ``STOP_ATR_MULT × ATR`` → 止损信号
金字塔加仓             关键点上方 1 / 2 / 3 倍 ATR 分三级加仓位
危险信号               假突破（突破后数根内收回）、高位放量滞涨
====================  ==========================================================

与 ``technical_analysis.find_support_resistance()`` 的区别
---------------------------------------------------------
后者是**双向对称的静态支撑压力位**（下方低吸 / 上方减仓），用 Swing Pivot 聚类得到；
本模块是**单向的突破触发价**（只在周线向上时用，要求放量，带止损与加仓位）。
两者可以同时存在，但语义不同，不要互相替代。

数据不足时的降级
----------------
观察池中约 145 只标的目前只有 ~120 根日线（< 250），因此：

- 不假设存在 52 周新高，改用「可用区间高点」（``range_high``）并标注根数；
- 周线不足 60 根时潮汐自动降级周期（20/60 → 10/30 → 5/20），并回报 ``tide_period``；
- 日线不足 ``MIN_BARS`` 根直接跳过该标的。

纯计算层：``analyze_livermore()`` 不做任何 IO；``scan_livermore()`` 负责读库汇总。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

# ── 信号类型 ───────────────────────────────────────────────────────────────────

SIG_BREAK_REVERSAL = "LIV_PIVOT_BREAK_REVERSAL"        # 反转关键点突破（建仓）
SIG_BREAK_CONTINUATION = "LIV_PIVOT_BREAK_CONTINUATION"  # 连续关键点突破（加仓）
SIG_NEAR_PIVOT = "LIV_NEAR_PIVOT"                      # 逼近关键点（预备）
SIG_FAILED_BREAKOUT = "LIV_FAILED_BREAKOUT"            # 假突破（离场）
SIG_STOP_TRIGGERED = "LIV_STOP_TRIGGERED"              # 跌破关键点（止损）
SIG_CLIMAX_WARNING = "LIV_CLIMAX_WARNING"              # 高位放量滞涨（危险）

#: 信号 → 操作方向。bullish=True 为做多类，False 为离场/预警类。
SIGNAL_BULLISH: dict[str, bool] = {
    SIG_BREAK_REVERSAL: True,
    SIG_BREAK_CONTINUATION: True,
    SIG_NEAR_PIVOT: True,
    SIG_FAILED_BREAKOUT: False,
    SIG_STOP_TRIGGERED: False,
    SIG_CLIMAX_WARNING: False,
}

SIGNAL_LABEL: dict[str, str] = {
    SIG_BREAK_REVERSAL: "反转关键点突破",
    SIG_BREAK_CONTINUATION: "连续关键点突破",
    SIG_NEAR_PIVOT: "逼近关键点",
    SIG_FAILED_BREAKOUT: "假突破",
    SIG_STOP_TRIGGERED: "跌破关键点",
    SIG_CLIMAX_WARNING: "放量滞涨",
}

# ── 默认参数（可被 config.LIV_* 覆盖，见 config.py）────────────────────────────

PLATFORM_LOOKBACK = 60        # 平台搜索最长窗口（根）
PLATFORM_MIN_BARS = 10        # 平台最短根数
PLATFORM_MAX_RANGE_PCT = 0.14  # 平台真实振幅上限（high/low，占收盘价）
PLATFORM_MAX_RANGE_ATR = 5.0  # 平台真实振幅上限（ATR 倍数）
PLATFORM_MAX_NET_RATIO = 0.60  # 净位移 / 真实振幅 上限（排除单边趋势）
MAX_HOLD_BARS = 12            # 突破后最多回看几根去找平台
BREAKOUT_BUFFER = 0.002       # 突破缓冲：收盘需高于关键点 0.2%
VOL_CONFIRM_RATIO = 1.5       # 放量确认阈值
VOL_DRY_RATIO = 0.8           # 缩量阈值
NEAR_PIVOT_PCT = 2.0          # 「逼近关键点」阈值（%）
STOP_ATR_MULT = 0.5           # 止损：关键点下方几倍 ATR
FAILED_BREAKOUT_BARS = 3      # 突破后几根内收回算假突破
STOP_LOOKBACK_BARS = 15       # 止损判定：近几根内曾突破
CLIMAX_VOL_RATIO = 2.0        # 放量滞涨：量比阈值
CLIMAX_MAX_GAIN = 0.5         # 放量滞涨：当日涨幅上限（%）
CLIMAX_MIN_RSI = 70           # 放量滞涨：RSI12 下限
CLIMAX_NEAR_HIGH = 0.90       # 放量滞涨：需在区间高点的此比例之上
LEADER_RS60 = 5.0             # 龙头判定：60 日相对强度下限（%）
MIN_BARS = 40                 # 日线最少根数

#: 潮汐周期降级顺序（由长到短）
_TIDE_PERIODS: tuple[tuple[int, int], ...] = ((20, 60), (10, 30), (5, 20))


# ── 数据结构 ───────────────────────────────────────────────────────────────────


@dataclass
class LivermoreSignal:
    """单条利弗莫尔信号。"""

    signal_type: str
    strength: float          # 0~1
    description: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class LivermoreResult:
    """单只标的的关键点全景 + 信号列表。"""

    panorama: dict[str, Any] = field(default_factory=dict)
    signals: list[LivermoreSignal] = field(default_factory=list)


# ── 通用工具 ───────────────────────────────────────────────────────────────────


def _to_native(obj: Any) -> Any:
    """递归把 numpy 标量转成原生 Python 类型。

    FastAPI 的 jsonable_encoder 无法序列化 numpy.bool_ / numpy.float64，
    直接返回会让端点 500。所有对外结构统一过一道这里。
    """
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(v) for v in obj]
    if isinstance(obj, bool):
        return bool(obj)
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        return None if math.isnan(obj) else float(obj)
    if hasattr(obj, "item"):  # numpy 标量兜底
        try:
            return _to_native(obj.item())
        except (ValueError, AttributeError):
            return obj
    return obj


def _num(v: Any) -> float | None:
    """宽容地转 float，None / NaN / 非法值一律返回 None。"""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _arr(df: pd.DataFrame, col: str) -> list[float | None]:
    """取列并转成 float/None 列表，容忍 object dtype 与 None。"""
    if col not in df.columns:
        return [None] * len(df)
    return [_num(v) for v in pd.to_numeric(df[col], errors="coerce").tolist()]


def _pct_change(closes: list[float | None], n: int) -> float | None:
    """最近 n 根的涨跌幅（%）。数据不足或分母非法返回 None。"""
    if len(closes) <= n:
        return None
    cur, prev = closes[-1], closes[-1 - n]
    if cur is None or prev is None or prev <= 0:
        return None
    return (cur - prev) / prev * 100


def _clamp(v: float, lo: float = 0.05, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# ── 周线潮汐 ───────────────────────────────────────────────────────────────────


def weekly_tide(weekly_df: pd.DataFrame) -> tuple[str, list[int] | None, str]:
    """周线潮汐方向。数据不足时自动降级周期。

    Returns:
        ``(tide, period, note)``；tide ∈ ``up`` / ``down`` / ``neutral`` / ``unknown``。

    Note:
        ``config.WEEKLY_INDICATOR_CONFIG`` 此前**未配置 ma**，所以
        ``kline_indicators`` 里 1w 的 ma20/ma60 全为 NULL（已确认）。
        这里先用指标表（若已补齐），否则用周线收盘价现算。
    """
    if weekly_df is None or weekly_df.empty or "close" not in weekly_df.columns:
        return "unknown", None, "无周线数据"

    last = weekly_df.iloc[-1]
    db_fast, db_slow = _num(last.get("ma20")), _num(last.get("ma60"))
    if db_fast is not None and db_slow is not None:
        tide = "up" if db_fast > db_slow else "down" if db_fast < db_slow else "neutral"
        return tide, [20, 60], "指标表"

    closes = [v for v in _arr(weekly_df, "close") if v is not None]
    n = len(closes)
    for fast, slow in _TIDE_PERIODS:
        if n >= slow:
            f = sum(closes[-fast:]) / fast
            s = sum(closes[-slow:]) / slow
            tide = "up" if f > s else "down" if f < s else "neutral"
            note = "标准周期" if (fast, slow) == (20, 60) else f"周期降级（周线仅 {n} 根）"
            return tide, [fast, slow], note

    return "unknown", None, f"周线仅 {n} 根，不足以判断潮汐"


# ── 关键点（整理平台）识别 ─────────────────────────────────────────────────────


def _longest_platform_at(
    highs: list[float | None],
    lows: list[float | None],
    closes: list[float | None],
    atr: float | None,
    end_idx: int,
    *,
    lookback: int,
    min_bars: int,
    max_range_pct: float,
    atr_mult: float,
    max_net_ratio: float,
) -> dict | None:
    """求以 end_idx 结尾的**最长**窄幅整理窗口。

    从右往左扩展窗口（长度递增），最长 lookback 根、最短 min_bars 根。三个约束：

    1. **真实振幅** ``(max(high) − min(low)) / 收盘 ≤ max_range_pct``
    2. **真实振幅** ``≤ atr × atr_mult``
    3. **净位移 / 真实振幅 ≤ max_net_ratio** —— 排除单边趋势被误判成"平台"

    箱体上/下沿取窗口内 **收盘价的最高/最低**（而非最高/最低价）：
    单根插针影线会把"压力位"抬到不现实的位置，用收盘价定义更抗噪，
    也让突破触发价（收盘价越过上沿）与判定口径一致。
    """
    ref_close = closes[end_idx]
    if ref_close is None or ref_close <= 0:
        return None

    run_hi: float | None = None
    run_lo: float | None = None
    run_hi_c: float | None = None
    run_lo_c: float | None = None
    best: dict | None = None
    max_len = min(lookback, end_idx + 1)

    for length in range(1, max_len + 1):
        i = end_idx - length + 1
        hi, lo, cl = highs[i], lows[i], closes[i]
        if hi is not None:
            run_hi = hi if run_hi is None else max(run_hi, hi)
        if lo is not None:
            run_lo = lo if run_lo is None else min(run_lo, lo)
        if cl is not None:
            run_hi_c = cl if run_hi_c is None else max(run_hi_c, cl)
            run_lo_c = cl if run_lo_c is None else min(run_lo_c, cl)
        if run_hi is None or run_lo is None or run_hi_c is None or length < min_bars:
            continue

        amp = run_hi - run_lo               # 真实振幅
        if amp <= 0:
            continue
        if amp / ref_close > max_range_pct:
            continue
        if atr and atr > 0 and amp > atr * atr_mult:
            continue
        start_close = closes[i]
        if start_close is None:
            continue
        if abs(ref_close - start_close) / amp > max_net_ratio:
            continue

        best = {
            "start_idx": i,
            "end_idx": end_idx,
            "upper": float(run_hi_c),
            "lower": float(run_lo_c),
            "max_high": float(run_hi),
            "min_low": float(run_lo),
            "bars": length,
            "range_pct": round((run_hi_c - run_lo_c) / ref_close * 100, 2),
            "amp_pct": round(amp / ref_close * 100, 2),
        }
    return best


def find_platform(
    df: pd.DataFrame,
    *,
    lookback: int = PLATFORM_LOOKBACK,
    min_bars: int = PLATFORM_MIN_BARS,
    max_range_pct: float = PLATFORM_MAX_RANGE_PCT,
    atr_mult: float = PLATFORM_MAX_RANGE_ATR,
    max_net_ratio: float = PLATFORM_MAX_NET_RATIO,
    max_hold: int = MAX_HOLD_BARS,
) -> dict | None:
    """找出当前最具参考价值的整理平台（关键点来源）。

    从 ``total-2`` 往前最多 ``max_hold`` 个锚点各求一次最长窗口，
    再取「根数最多、同根数取更新」的那个 —— 这样既能在平台内找到横盘箱体，
    也能在刚突破数根后仍找到突破前的那个箱体。
    """
    total = len(df)
    if total < min_bars + 2:
        return None

    highs = _arr(df, "high")
    lows = _arr(df, "low")
    closes = _arr(df, "close")
    atrs = _arr(df, "atr14")

    candidates: list[dict] = []
    for anchor in range(total - 2, max(total - 2 - max_hold, -1), -1):
        if anchor < min_bars:
            break
        plat = _longest_platform_at(
            highs, lows, closes, atrs[anchor], anchor,
            lookback=lookback, min_bars=min_bars,
            max_range_pct=max_range_pct, atr_mult=atr_mult,
            max_net_ratio=max_net_ratio,
        )
        if plat:
            candidates.append(plat)

    if not candidates:
        return None
    # 优先根数最多（箱体越长越有效），同根数取结束更晚（更新）的
    candidates.sort(key=lambda p: (-p["bars"], -p["end_idx"]))
    return candidates[0]


# ── 主分析函数 ─────────────────────────────────────────────────────────────────


def analyze_livermore(
    df: pd.DataFrame,
    weekly_df: pd.DataFrame | None = None,
    *,
    code: str = "",
    name: str = "",
    bench_ret_20: float | None = None,
    bench_ret_60: float | None = None,
    require_tide_up: bool = True,
    params: dict[str, Any] | None = None,
) -> LivermoreResult:
    """对单只标的做利弗莫尔关键点分析。

    Parameters
    ----------
    df :
        日线 DataFrame（日期升序，含 OHLCV + ma20/ma60/atr14/vol_ma20/rsi12）。
    weekly_df :
        周线 DataFrame，仅用于算潮汐。
    bench_ret_20 / bench_ret_60 :
        基准（SPY）最近 20 / 60 根涨幅（%），用于相对强度。
    require_tide_up :
        True 时只有 ``tide == "up"`` 才产出做多突破信号（离场/预警信号不受限）。
    params :
        覆盖本模块默认参数的字典（键名同模块常量，小写）。

    Returns
    -------
    LivermoreResult（``panorama`` 为原生类型字典，可直接 JSON 序列化）
    """
    p = _resolve_params(params)
    panorama: dict[str, Any] = {
        "code": code,
        "name": name,
        "date": "",
        "daily_bars": 0,
        "weekly_bars": 0,
        "state": "unknown",
        "context": "none",
    }
    if df is None or df.empty or len(df) < p["MIN_BARS"]:
        panorama["skip_reason"] = f"日线不足 {p['MIN_BARS']} 根"
        return LivermoreResult(_to_native(panorama), [])

    total = len(df)
    closes = _arr(df, "close")
    highs = _arr(df, "high")
    lows = _arr(df, "low")
    volumes = _arr(df, "volume")
    vol_ma20 = _arr(df, "vol_ma20")

    last_date = str(df.iloc[-1].get("date", "") or "")
    close = closes[-1]
    if close is None or close <= 0:
        panorama["skip_reason"] = "最新收盘价缺失"
        return LivermoreResult(_to_native(panorama), [])

    # ── 趋势：周线潮汐 + 日线波浪 ──
    tide, tide_period, tide_note = weekly_tide(weekly_df) if weekly_df is not None else ("unknown", None, "无周线")
    ma20 = _num(df.iloc[-1].get("ma20"))
    ma60 = _num(df.iloc[-1].get("ma60"))
    wave = "unknown"
    if ma20 is not None and ma60 is not None:
        wave = "up" if ma20 > ma60 else "down" if ma20 < ma60 else "neutral"

    # ── 关键点：整理平台上沿 ──
    plat = find_platform(
        df,
        lookback=p["PLATFORM_LOOKBACK"],
        min_bars=p["PLATFORM_MIN_BARS"],
        max_range_pct=p["PLATFORM_MAX_RANGE_PCT"],
        atr_mult=p["PLATFORM_MAX_RANGE_ATR"],
        max_net_ratio=p["PLATFORM_MAX_NET_RATIO"],
        max_hold=p["MAX_HOLD_BARS"],
    )

    # ── 量能 ──
    vol_ratio = None
    if volumes[-1] is not None and vol_ma20[-1] and vol_ma20[-1] > 0:
        vol_ratio = volumes[-1] / vol_ma20[-1]

    # ── 相对强度 ──
    ret_20 = _pct_change(closes, 20)
    ret_60 = _pct_change(closes, 60)
    rs_20 = None if (ret_20 is None or bench_ret_20 is None) else ret_20 - bench_ret_20
    rs_60 = None if (ret_60 is None or bench_ret_60 is None) else ret_60 - bench_ret_60
    is_leader = bool(rs_60 is not None and rs_60 >= p["LEADER_RS60"])

    panorama.update({
        "date": last_date,
        "daily_bars": total,
        "weekly_bars": 0 if weekly_df is None or weekly_df.empty else len(weekly_df),
        "close": round(close, 4),
        "tide": tide,
        "tide_period": tide_period,
        "tide_note": tide_note,
        "wave": wave,
        "ma20": ma20,
        "ma60": ma60,
        "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
        "ret_20": round(ret_20, 2) if ret_20 is not None else None,
        "ret_60": round(ret_60, 2) if ret_60 is not None else None,
        "rs_20": round(rs_20, 2) if rs_20 is not None else None,
        "rs_60": round(rs_60, 2) if rs_60 is not None else None,
        "is_leader": is_leader,
        "pivotal": None,
        "platform_upper": None,
        "platform_lower": None,
        "platform_bars": None,
        "platform_range_pct": None,
        "platform_start_date": None,
        "platform_stop_date": None,
        "prior_high": None,
        "prior_high_dist_pct": None,
        "breakout_is_new_high": False,
        "new_high_250": None,
        "dist_pct": None,
        "days_above": 0,
        "stop": None,
        "stop_dist_pct": None,
        "pyramid": [],
        "range_high": None,
        "range_high_bars": 0,
        "range_high_dist_pct": None,
        "high_250": None,
        "has_250_bars": total >= 250,
    })

    if plat is None:
        panorama["state"] = "no_platform"
        panorama["skip_reason"] = "近 %d 根内无有效整理平台" % p["PLATFORM_LOOKBACK"]
        return LivermoreResult(_to_native(panorama), [])

    end_idx = plat["end_idx"]
    start_idx = plat["start_idx"]
    upper = plat["upper"]
    lower = plat["lower"]
    dates = df["date"].tolist() if "date" in df.columns else []

    # ── 反转 / 连续 关键点：平台建立时的中期趋势方向 ──
    ma20_e = _num(df.iloc[end_idx].get("ma20"))
    ma60_e = _num(df.iloc[end_idx].get("ma60"))
    if ma20_e is not None and ma60_e is not None:
        context = "continuation" if ma20_e > ma60_e else "reversal"
    else:
        context = "reversal"

    # ── 关键点上方已连续几根（判定「今日首破」还是「已突破」）──
    buffer_price = upper * (1 + p["BREAKOUT_BUFFER"])
    days_above = 0
    probe = total - 1
    while probe >= 0 and closes[probe] is not None and closes[probe] > buffer_price:
        days_above += 1
        probe -= 1

    dist_pct = (close - upper) / upper * 100

    # ── 区间高点（数据不足 250 根时退化使用）──
    seg = [h for h in highs[: end_idx + 1] if h is not None]
    range_high = max(seg) if seg else None
    range_high_bars = end_idx + 1
    range_high_dist = ((close - range_high) / range_high * 100) if range_high else None
    seg250 = [h for h in highs[-250:] if h is not None]
    high_250 = max(seg250) if total >= 250 and seg250 else None

    # ── 前高：平台开始之前的区间最高点（越过它才是真正的创新高突破）──
    prior_high = None
    if start_idx > 0:
        seg_prior = [h for h in highs[:start_idx] if h is not None]
        prior_high = max(seg_prior) if seg_prior else None

    # ── 止损与金字塔加仓位 ──
    atr = _num(df.iloc[-1].get("atr14"))
    if atr is None or atr <= 0:
        atr = close * 0.02
    stop = max(upper - p["STOP_ATR_MULT"] * atr, lower)
    stop_dist_pct = (close - stop) / close * 100
    pyramid = [
        {
            "level": i,
            "price": round(upper + i * atr, 4),
            "pct_from_pivotal": round(i * atr / upper * 100, 2),
            "reached": bool(close >= upper + i * atr),
        }
        for i in (1, 2, 3)
    ]

    prior_high_dist = ((close - prior_high) / prior_high * 100) if prior_high else None

    panorama.update({
        "state": (
            "above" if days_above > 0
            else "approaching" if dist_pct is not None and -p["NEAR_PIVOT_PCT"] <= dist_pct <= 0
            else "below" if dist_pct is not None and dist_pct < 0
            else "platform"
        ),
        "context": context,
        "pivotal": round(upper, 4),
        "platform_upper": round(upper, 4),
        "platform_lower": round(lower, 4),
        "platform_bars": plat["bars"],
        "platform_range_pct": plat["range_pct"],
        "platform_amp_pct": plat.get("amp_pct"),
        "platform_start_date": str(dates[start_idx]) if start_idx < len(dates) else None,
        "platform_stop_date": str(dates[end_idx]) if end_idx < len(dates) else None,
        # 供前端在 K 线图上定位箱体区间（从最后一根往前数）
        "platform_start_bars_ago": total - 1 - start_idx,
        "platform_end_bars_ago": total - 1 - end_idx,
        "prior_high": round(prior_high, 4) if prior_high is not None else None,
        "prior_high_dist_pct": round(prior_high_dist, 2) if prior_high_dist is not None else None,
        "breakout_is_new_high": bool(prior_high is not None and close > prior_high),
        "new_high_250": (bool(close >= high_250) if high_250 is not None else None),
        "dist_pct": round(dist_pct, 2),
        "days_above": days_above,
        "atr14": round(atr, 4),
        "stop": round(stop, 4),
        "stop_dist_pct": round(stop_dist_pct, 2),
        "pyramid": pyramid,
        "range_high": round(range_high, 4) if range_high is not None else None,
        "range_high_bars": range_high_bars,
        "range_high_dist_pct": round(range_high_dist, 2) if range_high_dist is not None else None,
        "high_250": round(high_250, 4) if high_250 is not None else None,
    })

    signals = _build_signals(
        panorama=panorama,
        closes=closes,
        p=p,
        upper=upper,
        days_above=days_above,
        dist_pct=dist_pct,
        context=context,
        tide=tide,
        wave=wave,
        vol_ratio=vol_ratio,
        rsi12=_num(df.iloc[-1].get("rsi12")),
        stop=stop,
        is_leader=is_leader,
        range_high=range_high,
        require_tide_up=require_tide_up,
    )
    return LivermoreResult(_to_native(panorama), signals)


def _build_signals(
    *,
    panorama: dict[str, Any],
    closes: list[float | None],
    p: dict[str, Any],
    upper: float,
    days_above: int,
    dist_pct: float,
    context: str,
    tide: str,
    wave: str,
    vol_ratio: float | None,
    rsi12: float | None,
    stop: float,
    is_leader: bool,
    range_high: float | None,
    require_tide_up: bool,
) -> list[LivermoreSignal]:
    """按优先级生成信号（同一标的可同时有做多与预警信号）。"""
    out: list[LivermoreSignal] = []
    date = panorama["date"]
    close = panorama["close"]
    buffer_price = upper * (1 + p["BREAKOUT_BUFFER"])

    def _detail(extra: dict[str, Any] | None = None) -> dict[str, Any]:
        base = {
            "date": date,
            "close": close,
            "pivotal": panorama["pivotal"],
            "platform_upper": panorama["platform_upper"],
            "platform_lower": panorama["platform_lower"],
            "platform_bars": panorama["platform_bars"],
            "platform_range_pct": panorama["platform_range_pct"],
            "platform_start_date": panorama["platform_start_date"],
            "prior_high": panorama["prior_high"],
            "dist_pct": panorama["dist_pct"],
            "days_above": days_above,
            "vol_ratio": panorama["vol_ratio"],
            "tide": tide,
            "tide_period": panorama.get("tide_period"),
            "wave": wave,
            "context": context,
            "stop": panorama["stop"],
            "stop_dist_pct": panorama["stop_dist_pct"],
            "pyramid": panorama["pyramid"],
            "rs_60": panorama.get("rs_60"),
            "rs_20": panorama.get("rs_20"),
            "is_leader": is_leader,
            "range_high": panorama.get("range_high"),
            "range_high_bars": panorama.get("range_high_bars"),
            "atr14": panorama.get("atr14"),
            "daily_bars": panorama.get("daily_bars"),
            "weekly_bars": panorama.get("weekly_bars"),
        }
        if extra:
            base.update(extra)
        return base

    def _base_strength(breakout_pct: float) -> float:
        s = 0.45
        if vol_ratio is not None:
            if vol_ratio >= p["VOL_CONFIRM_RATIO"]:
                s += 0.15
            elif vol_ratio < p["VOL_DRY_RATIO"]:
                s -= 0.10
        if tide == "up":
            s += 0.12
        elif tide == "down":
            s -= 0.10
        if is_leader:
            s += 0.10
        s += min(max(breakout_pct, 0.0) / 3.0, 1.0) * 0.10
        if (panorama.get("platform_bars") or 0) >= 30:
            s += 0.08
        if context == "continuation":
            s += 0.05
        return s

    # ── 1. 关键点突破（今日首次收于关键点上方）──
    if days_above == 1:
        breakout_pct = dist_pct
        strength = _clamp(_base_strength(breakout_pct))
        confirmed = vol_ratio is not None and vol_ratio >= p["VOL_CONFIRM_RATIO"]
        if context == "continuation":
            sig_type, kind = SIG_BREAK_CONTINUATION, "连续关键点"
            action = "趋势延续，可顺势加仓"
        else:
            sig_type, kind = SIG_BREAK_REVERSAL, "反转关键点"
            action = "趋势反转确认，可分批建仓"

        vol_txt = f"量比{vol_ratio:.2f}" if vol_ratio is not None else "量比—"
        vol_flag = "放量确认" if confirmed else ("无量突破，需谨慎" if vol_ratio is not None and vol_ratio < p["VOL_DRY_RATIO"] else "量能一般")
        if tide != "up" and require_tide_up:
            action = "⚠️ 逆潮汐突破，建议只做观察不下单"

        out.append(LivermoreSignal(
            signal_type=sig_type,
            strength=strength,
            description=(
                f"{kind}突破 {upper:.2f}（现价 {close:.2f} / +{breakout_pct:.2f}%），"
                f"{vol_txt} {vol_flag}；潮汐 {tide} / 波浪 {wave}"
            ),
            detail=_detail({
                "kind": kind,
                "action": action,
                "volume_confirmed": confirmed,
                "breakout_pct": round(breakout_pct, 2),
            }),
        ))

    # ── 先判定「假突破」与「跌破止损」，二者都会否决「逼近关键点」的做多语义 ──
    # 假突破：近 N 根内曾收于关键点上方，今日收回下方
    is_failed = False
    if days_above == 0 and len(closes) > p["FAILED_BREAKOUT_BARS"] + 1:
        window = [c for c in closes[-(p["FAILED_BREAKOUT_BARS"] + 1):-1] if c is not None]
        is_failed = bool(window and max(window) > buffer_price and close < upper)

    # 跌破止损：近 STOP_LOOKBACK_BARS 根内出现过突破，且现价已在止损位下方。
    # ⚠️ 止损位只在**突破之后**才有意义；未突破时价格在关键点下方属正常，不能据此否决。
    is_stopped = False
    if len(closes) > p["STOP_LOOKBACK_BARS"]:
        hist = [c for c in closes[-(p["STOP_LOOKBACK_BARS"] + 1):-1] if c is not None]
        is_stopped = bool(hist and max(hist) > buffer_price and close < stop)

    # ── 2. 逼近关键点（未突破、在下方 NEAR_PIVOT_PCT 内，且未假突破/未止损）──
    if (
        days_above == 0
        and -p["NEAR_PIVOT_PCT"] <= dist_pct <= 0
        and not is_failed
        and not is_stopped
    ):
        gap = abs(dist_pct)
        strength = 0.35 + (1 - gap / p["NEAR_PIVOT_PCT"]) * 0.25
        if tide == "up":
            strength += 0.15
        if is_leader:
            strength += 0.10
        out.append(LivermoreSignal(
            signal_type=SIG_NEAR_PIVOT,
            strength=_clamp(strength),
            description=(
                f"距关键点 {upper:.2f} 仅 {gap:.2f}%（现价 {close:.2f}），"
                f"突破且放量方为买点；潮汐 {tide}"
            ),
            detail=_detail({"kind": "逼近关键点", "gap_pct": round(gap, 2)}),
        ))

    # ── 3. 假突破（离场信号）──
    if is_failed:
        out.append(LivermoreSignal(
            signal_type=SIG_FAILED_BREAKOUT,
            strength=_clamp(0.55 + (0.15 if vol_ratio and vol_ratio >= p["VOL_CONFIRM_RATIO"] else 0.0)),
            description=(
                f"近 {p['FAILED_BREAKOUT_BARS']} 根内曾突破 {upper:.2f}，"
                f"今日收回下方（收 {close:.2f}）→ 假突破，按利弗莫尔原则应离场"
            ),
            detail=_detail({"kind": "假突破", "action": "突破失败，减仓/离场"}),
        ))

    # ── 4. 跌破关键点止损 ──
    if is_stopped:
        out.append(LivermoreSignal(
            signal_type=SIG_STOP_TRIGGERED,
            strength=_clamp(0.70 + min((stop - close) / stop, 0.15) * 2),
            description=(
                f"跌破止损位 {stop:.2f}（关键点 {upper:.2f} − {p['STOP_ATR_MULT']}×ATR，"
                f"现价 {close:.2f}）→ 触发止损"
            ),
            detail=_detail({"kind": "跌破关键点", "action": "触发止损，离场"}),
        ))

    # ── 5. 高位放量滞涨（利弗莫尔「危险信号」）──
    if len(closes) >= 2 and closes[-1] is not None and closes[-2]:
        gain_pct = (closes[-1] - closes[-2]) / closes[-2] * 100
    else:
        gain_pct = None
    if (
        vol_ratio is not None and vol_ratio >= p["CLIMAX_VOL_RATIO"]
        and gain_pct is not None and gain_pct <= p["CLIMAX_MAX_GAIN"]
        and rsi12 is not None and rsi12 >= p["CLIMAX_MIN_RSI"]
        and range_high is not None and close >= range_high * p["CLIMAX_NEAR_HIGH"]
    ):
        out.append(LivermoreSignal(
            signal_type=SIG_CLIMAX_WARNING,
            strength=_clamp(0.50 + min(vol_ratio - p["CLIMAX_VOL_RATIO"], 1.5) * 0.15),
            description=(
                f"高位放量滞涨：量比 {vol_ratio:.2f} 但涨幅仅 {gain_pct:.2f}%、"
                f"RSI12 {rsi12:.1f}，且已接近区间高点 → 注意派发"
            ),
            detail=_detail({
                "kind": "放量滞涨",
                "action": "危险信号，收紧止损/部分止盈",
                "gain_pct": round(gain_pct, 2),
                "rsi12": round(rsi12, 1),
            }),
        ))

    # 把可读描述与类型冗余进 detail —— 落库后前端/回测只读 detail_json 也能拿到
    for s in out:
        s.detail.setdefault("description", s.description)
        s.detail.setdefault("signal_type", s.signal_type)

    # 高优先级在前：突破 > 止损 > 假突破 > 滞涨 > 逼近
    order = {
        SIG_BREAK_CONTINUATION: 0,
        SIG_BREAK_REVERSAL: 0,
        SIG_STOP_TRIGGERED: 1,
        SIG_FAILED_BREAKOUT: 2,
        SIG_CLIMAX_WARNING: 3,
        SIG_NEAR_PIVOT: 4,
    }
    out.sort(key=lambda s: (order.get(s.signal_type, 9), -s.strength))
    return out


# ── 参数解析 ───────────────────────────────────────────────────────────────────


#: 可被 config.LIV_* / 调用方覆盖的参数名（显式列出，避免误收信号常量）
TUNABLE_PARAMS: tuple[str, ...] = (
    "PLATFORM_LOOKBACK",
    "PLATFORM_MIN_BARS",
    "PLATFORM_MAX_RANGE_PCT",
    "PLATFORM_MAX_RANGE_ATR",
    "PLATFORM_MAX_NET_RATIO",
    "MAX_HOLD_BARS",
    "BREAKOUT_BUFFER",
    "VOL_CONFIRM_RATIO",
    "VOL_DRY_RATIO",
    "NEAR_PIVOT_PCT",
    "STOP_ATR_MULT",
    "FAILED_BREAKOUT_BARS",
    "STOP_LOOKBACK_BARS",
    "CLIMAX_VOL_RATIO",
    "CLIMAX_MAX_GAIN",
    "CLIMAX_MIN_RSI",
    "CLIMAX_NEAR_HIGH",
    "LEADER_RS60",
    "MIN_BARS",
)


def _resolve_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """合并模块默认参数与外部覆盖（config.LIV_*）。"""
    p = {k: globals()[k] for k in TUNABLE_PARAMS}
    if params:
        p.update({k: v for k, v in params.items() if v is not None and k in p})
    return p


# ── 全池扫描 ───────────────────────────────────────────────────────────────────


def _bench_returns(spy_df: pd.DataFrame | None) -> tuple[float | None, float | None]:
    """基准（SPY）20 / 60 根涨幅。"""
    if spy_df is None or spy_df.empty:
        return None, None
    closes = _arr(spy_df, "close")
    return _pct_change(closes, 20), _pct_change(closes, 60)


def scan_livermore(
    codes: list[str] | None = None,
    *,
    date: str | None = None,
    require_tide_up: bool = True,
    daily_bars: int = 300,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """扫描全池，返回按用途分组的利弗莫尔关键点结果。

    只读 ``kline_indicators``，不写库；写库由调用方（CLI / scan-signals）负责。

    Returns
    -------
    dict:
        ``date`` / ``universe`` / ``stats`` / ``panoramas``（全部标的）
        / ``breakouts`` / ``near_pivots`` / ``above_pivot`` / ``dangers``
        / ``filtered_by_tide``（因逆潮汐被挡掉的突破数）
    """
    from trader_analysis.futu_strategy import config as _cfg
    from trader_analysis.futu_strategy.storage import query_recent

    if codes is None:
        codes = list(_cfg.WATCHLIST)

    # 从 config.LIV_* 读取可调参数（未配置的沿用模块默认值）
    lv_params: dict[str, Any] = {}
    for key in TUNABLE_PARAMS:
        v = getattr(_cfg, f"LIV_{key}", None)
        if v is not None:
            lv_params[key] = v
    if params:
        lv_params.update(params)

    spy_df = query_recent("US.SPY", "1d", limit=daily_bars)
    if date and not spy_df.empty:
        spy_df = spy_df[spy_df["date"].astype(str) <= date]
    bench_ret_20, bench_ret_60 = _bench_returns(spy_df)

    names: dict[str, str] = {}
    try:
        from trader_analysis.futu_strategy.storage import _get_conn
        conn = _get_conn()
        names = {r["code"]: (r["name"] or "") for r in conn.execute("SELECT code, name FROM watchlist")}
        conn.close()
    except Exception:
        pass

    breakouts: list[dict] = []
    near_pivots: list[dict] = []
    above_pivot: list[dict] = []
    dangers: list[dict] = []
    panoramas: list[dict] = []
    skipped: list[dict] = []
    filtered_by_tide = 0
    signals_by_date: list[dict] = []
    data_date: str | None = None

    for code in codes:
        df = query_recent(code, "1d", limit=daily_bars)
        if df.empty or len(df) < MIN_BARS:
            skipped.append({"code": code, "name": names.get(code, ""), "reason": "日线数据不足", "daily_bars": len(df)})
            continue
        if date:
            df = df[df["date"].astype(str) <= date]
            if len(df) < MIN_BARS:
                skipped.append({"code": code, "name": names.get(code, ""), "reason": "指定日期前数据不足", "daily_bars": len(df)})
                continue
        weekly_df = query_recent(code, "1w", limit=200)
        if date and not weekly_df.empty:
            # 同样按日期截断，否则回溯时会用「未来」的周线算潮汐（前视偏差）
            weekly_df = weekly_df[weekly_df["date"].astype(str) <= date]

        res = analyze_livermore(
            df, weekly_df,
            code=code, name=names.get(code, ""),
            bench_ret_20=bench_ret_20, bench_ret_60=bench_ret_60,
            require_tide_up=require_tide_up, params=lv_params,
        )
        pan = res.panorama
        if not pan.get("pivotal"):
            skipped.append({
                "code": code,
                "name": names.get(code, ""),
                "reason": pan.get("skip_reason", "无有效整理平台"),
                "daily_bars": pan.get("daily_bars"),
                "close": pan.get("close"),
                "tide": pan.get("tide"),
            })
            continue
        panoramas.append(pan)
        if data_date is None:
            data_date = pan.get("date")

        item = dict(pan)
        for sig in res.signals:
            signals_by_date.append({
                "code": code,
                "date": pan.get("date"),
                "signal_type": sig.signal_type,
                "strength": sig.strength,
                "detail": sig.detail,
            })
            row = dict(item)
            row["signal_type"] = sig.signal_type
            row["signal_label"] = SIGNAL_LABEL.get(sig.signal_type, sig.signal_type)
            row["strength"] = round(sig.strength, 3)
            row["description"] = sig.description

            if sig.signal_type in (SIG_BREAK_REVERSAL, SIG_BREAK_CONTINUATION):
                if require_tide_up and pan.get("tide") != "up":
                    filtered_by_tide += 1
                    continue
                breakouts.append(row)
            elif sig.signal_type == SIG_NEAR_PIVOT:
                if require_tide_up and pan.get("tide") != "up":
                    filtered_by_tide += 1
                    continue
                near_pivots.append(row)
            else:
                # 止损 / 假突破 / 放量滞涨属风险提示，不受潮汐过滤
                dangers.append(row)

        # 「已在关键点上方」单独成组（供持仓/回踩加仓参考），同样受潮汐过滤
        if pan.get("state") == "above" and pan.get("days_above", 0) > 1:
            if require_tide_up and pan.get("tide") != "up":
                filtered_by_tide += 1
            else:
                above = dict(pan)
                above["signal_label"] = "已在关键点上方"
                above_pivot.append(above)

    def _sort_key(x: dict) -> tuple:
        return (not x.get("is_leader"), -(x.get("strength") or 0), -(x.get("rs_60") or -999))

    breakouts.sort(key=_sort_key)
    near_pivots.sort(key=_sort_key)
    above_pivot.sort(key=lambda x: (not x.get("is_leader"), -(x.get("rs_60") or -999)))

    # 危险信号：先按严重度（止损 > 假突破 > 放量滞涨）再按强度；同一标的只留最严重的一条
    # （止损与假突破常同时成立，两条都列在页面上是噪声；DB 里两条都会保留，供回测分别统计）
    _danger_order = {SIG_STOP_TRIGGERED: 0, SIG_FAILED_BREAKOUT: 1, SIG_CLIMAX_WARNING: 2}
    dangers.sort(key=lambda x: (_danger_order.get(x.get("signal_type", ""), 9), -(x.get("strength") or 0)))
    _deduped: list[dict] = []
    _seen: set[str] = set()
    for d in dangers:
        if d["code"] in _seen:
            continue
        _seen.add(d["code"])
        _deduped.append(d)
    dangers = _deduped

    tide_up = sum(1 for p in panoramas if p.get("tide") == "up")
    return _to_native({
        "date": date or data_date,
        "universe": len(codes),
        "scanned": len(panoramas),
        "require_tide_up": require_tide_up,
        "stats": {
            "breakouts": len(breakouts),
            "reversal": sum(1 for b in breakouts if b.get("context") == "reversal"),
            "continuation": sum(1 for b in breakouts if b.get("context") == "continuation"),
            "near_pivots": len(near_pivots),
            "above_pivot": len(above_pivot),
            "dangers": len(dangers),
            "dangers_stop": sum(1 for d in dangers if d.get("signal_type") == SIG_STOP_TRIGGERED),
            "dangers_failed": sum(1 for d in dangers if d.get("signal_type") == SIG_FAILED_BREAKOUT),
            "dangers_climax": sum(1 for d in dangers if d.get("signal_type") == SIG_CLIMAX_WARNING),
            "leaders": sum(1 for p in panoramas if p.get("is_leader")),
            "tide_up": tide_up,
            "tide_down": sum(1 for p in panoramas if p.get("tide") == "down"),
            "tide_unknown": sum(1 for p in panoramas if p.get("tide") in ("unknown", "neutral")),
            "filtered_by_tide": filtered_by_tide,
            "no_platform": len(skipped),
        },
        "bench": {
            "ret_20": round(bench_ret_20, 2) if bench_ret_20 is not None else None,
            "ret_60": round(bench_ret_60, 2) if bench_ret_60 is not None else None,
        },
        "breakouts": breakouts,
        "near_pivots": near_pivots,
        "above_pivot": above_pivot,
        "dangers": dangers,
        "panoramas": panoramas,
        "skipped": skipped,
        "signals": signals_by_date,
    })
