from __future__ import annotations

import numpy as np
import pandas as pd

from trader_analysis.data.schemas import OHLCVSchema
from trader_analysis.indicators.base import IndicatorSpec


def sma(df: pd.DataFrame, timeframe: str, period: int) -> pd.Series:
    """Simple Moving Average.

    Parameters
    ----------
    df:        OHLCV DataFrame（已包含目标周期的 K 线数据）
    timeframe: K 线维度，"1H" | "1D" | "1W" | "1M"
    period:    均线长度，如 5 / 60 / 200

    Returns
    -------
    pd.Series  命名为 "ma_{period}"，与输入 df 的索引对齐
    """
    col = OHLCVSchema.close
    if OHLCVSchema.timeframe in df.columns:
        data = df.loc[df[OHLCVSchema.timeframe] == timeframe, col]
    else:
        data = df[col]
    result = data.rolling(period, min_periods=period).mean()
    result.name = f"ma_{period}"
    return result


# ── 内部使用：Strategy / IndicatorSpec 管道 ──────────────────────────────────

def _sma_spec(period: int, *, col: str = OHLCVSchema.close, out_col: str | None = None) -> IndicatorSpec:
    name = out_col or f"sma_{period}"

    def _fn(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out[name] = out[col].rolling(period, min_periods=period).mean()
        return out

    return IndicatorSpec(name=f"sma({period})", fn=_fn, outputs=(name,))


def ema(span: int, *, col: str = OHLCVSchema.close, out_col: str | None = None) -> IndicatorSpec:
    name = out_col or f"ema_{span}"

    def _fn(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out[name] = out[col].ewm(span=span, adjust=False, min_periods=span).mean()
        return out

    return IndicatorSpec(name=f"ema({span})", fn=_fn, outputs=(name,))


def rsi(period: int = 14, *, col: str = OHLCVSchema.close, out_col: str | None = None) -> IndicatorSpec:
    name = out_col or f"rsi_{period}"

    def _fn(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        delta = out[col].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        out[name] = 100.0 - (100.0 / (1.0 + rs))
        return out

    return IndicatorSpec(name=f"rsi({period})", fn=_fn, outputs=(name,))


def macd(
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    *,
    col: str = OHLCVSchema.close,
    out_prefix: str = "macd",
) -> IndicatorSpec:
    macd_col = f"{out_prefix}_line"
    signal_col = f"{out_prefix}_signal"
    hist_col = f"{out_prefix}_hist"

    def _fn(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        ema_fast = out[col].ewm(span=fast, adjust=False, min_periods=fast).mean()
        ema_slow = out[col].ewm(span=slow, adjust=False, min_periods=slow).mean()
        out[macd_col] = ema_fast - ema_slow
        out[signal_col] = out[macd_col].ewm(span=signal, adjust=False, min_periods=signal).mean()
        out[hist_col] = out[macd_col] - out[signal_col]
        return out

    return IndicatorSpec(
        name=f"macd({fast},{slow},{signal})",
        fn=_fn,
        outputs=(macd_col, signal_col, hist_col),
    )


def atr(period: int = 14, *, out_col: str | None = None) -> IndicatorSpec:
    name = out_col or f"atr_{period}"

    def _fn(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        high = out[OHLCVSchema.high]
        low = out[OHLCVSchema.low]
        close = out[OHLCVSchema.close]
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                (high - low).abs(),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        out[name] = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        return out

    return IndicatorSpec(name=f"atr({period})", fn=_fn, outputs=(name,))


def bbands(
    period: int = 20,
    std_mult: float = 2.0,
    *,
    col: str = OHLCVSchema.close,
    out_prefix: str = "bb",
) -> IndicatorSpec:
    mid = f"{out_prefix}_mid_{period}"
    upper = f"{out_prefix}_upper_{period}"
    lower = f"{out_prefix}_lower_{period}"

    def _fn(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        m = out[col].rolling(period, min_periods=period).mean()
        s = out[col].rolling(period, min_periods=period).std(ddof=0)
        out[mid] = m
        out[upper] = m + std_mult * s
        out[lower] = m - std_mult * s
        return out

    return IndicatorSpec(name=f"bbands({period},{std_mult})", fn=_fn, outputs=(mid, upper, lower))
