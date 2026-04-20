"""通用指标计算层。

纯计算模块：接收 OHLCV DataFrame + 配置字典，追加技术指标列后返回。
不感知标的、不感知周期、不做阈值判断（判断逻辑归 scorer.py）。

底层使用 pandas 自实现（与 indicators/builtins.py 同源算法），无外部指标库依赖。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

# ── 内部数学函数 ──────────────────────────────────────────────────────────────

def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _macd(
    close: pd.Series, fast: int, slow: int, signal: int
) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    dif = ema_fast - ema_slow
    dea = _ema(dif, signal)
    hist = (dif - dea) * 2  # ×2 对齐富途/A 股显示口径
    return dif, dea, hist


def _bbands(
    close: pd.Series, length: int, std: float
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(length, min_periods=length).mean()
    s = close.rolling(length, min_periods=length).std(ddof=0)
    upper = mid + std * s
    lower = mid - std * s
    return upper, mid, lower


# ── 对外主函数 ────────────────────────────────────────────────────────────────

def calc_indicators(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """通用指标计算函数。

    Parameters
    ----------
    df     : 含 open/high/low/close/volume 列的 K 线 DataFrame。
             由调用方决定标的和周期，本函数完全不感知。
    config : 指标配置字典，示例见 config.DAILY_INDICATOR_CONFIG。

    Returns
    -------
    追加了指标列的 DataFrame（原始列保留）。
    开头的 NaN 属正常现象（预热期）。
    """
    df = df.copy()

    # MA（简单移动平均）
    for period in config.get("ma", []):
        df[f"ma{period}"] = _sma(df["close"], period)

    # EMA（指数移动平均，可选）
    for period in config.get("ema", []):
        df[f"ema{period}"] = _ema(df["close"], period)

    # RSI
    for period in config.get("rsi", []):
        df[f"rsi{period}"] = _rsi(df["close"], period)

    # MACD
    if "macd" in config:
        c = config["macd"]
        dif, dea, hist = _macd(df["close"], c["fast"], c["slow"], c["signal"])
        df["dif"] = dif
        df["dea"] = dea
        df["macd"] = hist

    # 布林带
    if "boll" in config:
        c = config["boll"]
        upper, mid, lower = _bbands(df["close"], c["length"], c["std"])
        df["boll_upper"] = upper
        df["boll_mid"] = mid
        df["boll_lower"] = lower

    # 成交量均线
    for period in config.get("vol_ma", []):
        df[f"vol_ma{period}"] = df["volume"].rolling(window=period).mean()

    return df


def detect_macd_divergence(
    df: pd.DataFrame, lookback: int = 60, distance: int = 5
) -> bool:
    """检测最近 lookback 根 K 线内是否存在 MACD 柱线底背离。

    底背离：价格创新低（low[idx2] < low[idx1]）但 MACD 柱线未创新低。
    前提：df 已经过 calc_indicators 计算，含 'macd' 和 'low' 列。
    """
    recent = df.tail(lookback).copy().reset_index(drop=True)

    if "macd" not in recent.columns or recent["macd"].isna().all():
        return False

    troughs, _ = find_peaks(-recent["low"].values, distance=distance)

    if len(troughs) < 2:
        return False

    idx1, idx2 = troughs[-2], troughs[-1]
    price_new_low = recent["low"].iloc[idx2] < recent["low"].iloc[idx1]
    macd_no_new_low = recent["macd"].iloc[idx2] > recent["macd"].iloc[idx1]

    return bool(price_new_low and macd_no_new_low)


def detect_panic_volume(
    df: pd.DataFrame, lookback: int = 20, panic_multiplier: float = 2.0
) -> bool:
    """检测最近 lookback 根 K 线内是否出现恐慌放量后缩量。

    条件一：峰值成交量 > vol_ma20 × panic_multiplier（恐慌放量）。
    条件二：峰值后近 3 根均量 < 峰值量 × 0.6（缩量回落）。
    前提：df 已经过 calc_indicators 计算，含 'vol_ma20' 列。
    """
    if "vol_ma20" not in df.columns:
        return False

    recent = df.tail(lookback).copy().reset_index(drop=True)
    peak_pos = int(recent["volume"].idxmax())

    vol_ma_val = recent["vol_ma20"].iloc[peak_pos]
    if pd.isna(vol_ma_val) or vol_ma_val == 0:
        return False

    is_panic = recent["volume"].iloc[peak_pos] > vol_ma_val * panic_multiplier

    after_peak = recent["volume"].iloc[peak_pos:]
    is_shrinking = (
        len(after_peak) >= 3
        and after_peak.tail(3).mean() < recent["volume"].iloc[peak_pos] * 0.6
    )

    return bool(is_panic and is_shrinking)
