from __future__ import annotations

import numpy as np
import pandas as pd

from trader_analysis.data.schemas import OHLCVSchema
from trader_analysis.indicators.base import IndicatorSpec


# ── Internal math helpers ─────────────────────────────────────────────────────
# These are called by both the public calc_* functions and the IndicatorSpec
# factories, ensuring a single source of truth for all indicator mathematics.

def _ema_s(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def _rsi_s(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _macd_s(
    close: pd.Series, fast: int, slow: int, signal: int
) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = _ema_s(close, fast)
    ema_slow = _ema_s(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema_s(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line  # line, signal, hist


def _bb_s(
    close: pd.Series, period: int, std_mult: float
) -> tuple[pd.Series, pd.Series, pd.Series]:
    m = close.rolling(period, min_periods=period).mean()
    s = close.rolling(period, min_periods=period).std(ddof=0)
    return m - std_mult * s, m, m + std_mult * s  # lower, mid, upper


# ── Public standalone calc functions (unified entry point) ────────────────────
# Use these in scoring systems, backtests, or any context that needs a raw
# Series instead of the IndicatorSpec pipeline.

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI series (Wilder smoothing). Unified entry point for RSI calculation."""
    return _rsi_s(close, period)


def calc_macd_hist(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.Series:
    """MACD histogram series. Unified entry point for MACD histogram."""
    _, _, hist = _macd_s(close, fast, slow, signal)
    return hist


def calc_bb_lower(
    close: pd.Series,
    period: int = 20,
    std_mult: float = 2.0,
) -> pd.Series:
    """Bollinger lower band series. Unified entry point for BB lower band."""
    lower, _, _ = _bb_s(close, period, std_mult)
    return lower


def calc_sma(close: pd.Series, period: int) -> pd.Series:
    """Simple moving average series. Unified entry point for SMA calculation."""
    return close.rolling(period, min_periods=period).mean()


# ── Standalone public function (original API) ─────────────────────────────────

def sma(df: pd.DataFrame, timeframe: str, period: int) -> pd.Series:
    """Simple Moving Average over a timeframe-filtered DataFrame.

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
    result = calc_sma(data, period)
    result.name = f"ma_{period}"
    return result


# ── IndicatorSpec factories (pipeline style) ──────────────────────────────────
# These wrap the calc_* / helper functions for use in the Strategy pipeline.

def _sma_spec(period: int, *, col: str = OHLCVSchema.close, out_col: str | None = None) -> IndicatorSpec:
    name = out_col or f"sma_{period}"

    def _fn(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out[name] = calc_sma(out[col], period)
        return out

    return IndicatorSpec(name=f"sma({period})", fn=_fn, outputs=(name,))


def ema(span: int, *, col: str = OHLCVSchema.close, out_col: str | None = None) -> IndicatorSpec:
    name = out_col or f"ema_{span}"

    def _fn(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out[name] = _ema_s(out[col], span)
        return out

    return IndicatorSpec(name=f"ema({span})", fn=_fn, outputs=(name,))


def rsi(period: int = 14, *, col: str = OHLCVSchema.close, out_col: str | None = None) -> IndicatorSpec:
    name = out_col or f"rsi_{period}"

    def _fn(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out[name] = _rsi_s(out[col], period)
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
        macd_line, sig_line, hist = _macd_s(out[col], fast, slow, signal)
        out[macd_col] = macd_line
        out[signal_col] = sig_line
        out[hist_col] = hist
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
        lower_s, mid_s, upper_s = _bb_s(out[col], period, std_mult)
        out[mid] = mid_s
        out[upper] = upper_s
        out[lower] = lower_s
        return out

    return IndicatorSpec(name=f"bbands({period},{std_mult})", fn=_fn, outputs=(mid, upper, lower))
