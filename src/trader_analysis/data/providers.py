from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from trader_analysis.data.schemas import OHLCVSchema, REQUIRED_OHLCV_COLUMNS


class DataProviderError(ValueError):
    pass


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def _coerce_ohlcv_types(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df[OHLCVSchema.timestamp] = pd.to_datetime(df[OHLCVSchema.timestamp], utc=False, errors="coerce")
    if df[OHLCVSchema.timestamp].isna().any():
        bad = int(df[OHLCVSchema.timestamp].isna().sum())
        raise DataProviderError(f"Failed to parse {bad} timestamp rows.")

    for col in [OHLCVSchema.open, OHLCVSchema.high, OHLCVSchema.low, OHLCVSchema.close]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if OHLCVSchema.volume in df.columns:
        df[OHLCVSchema.volume] = pd.to_numeric(df[OHLCVSchema.volume], errors="coerce").fillna(0.0)
    else:
        df[OHLCVSchema.volume] = 0.0

    if df[[OHLCVSchema.open, OHLCVSchema.high, OHLCVSchema.low, OHLCVSchema.close]].isna().any().any():
        raise DataProviderError("OHLC columns contain NaN after numeric coercion.")

    df = df.sort_values(OHLCVSchema.timestamp).reset_index(drop=True)
    return df


def normalize_ohlcv(
    df: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
) -> pd.DataFrame:
    df = _normalize_columns(df)
    missing = REQUIRED_OHLCV_COLUMNS - set(df.columns)
    if missing:
        raise DataProviderError(f"Missing required OHLCV columns: {sorted(missing)}")

    df = _coerce_ohlcv_types(df)

    if OHLCVSchema.symbol not in df.columns:
        df[OHLCVSchema.symbol] = symbol
    else:
        df[OHLCVSchema.symbol] = df[OHLCVSchema.symbol].astype(str).fillna(symbol)

    df[OHLCVSchema.timeframe] = timeframe
    return df


@dataclass
class CSVDataProvider:
    schema: OHLCVSchema = OHLCVSchema()

    def get_ohlcv_from_file(
        self,
        path: Path,
        *,
        symbol: str,
        timeframe: str,
        encoding: Optional[str] = None,
    ) -> pd.DataFrame:
        df = pd.read_csv(path, encoding=encoding)
        return normalize_ohlcv(df, symbol=symbol, timeframe=timeframe)


@dataclass
class FutuJsonDataProvider:
    """Reads Futu request_history_kline JSON format (real or mock).

    Expects the structure produced by futuapi/scripts/quote/get_kline.py:
    { "data": [ { "time_key": "...", "open": ..., "high": ...,
                  "low": ..., "close": ..., "volume": ..., ... } ] }
    """

    def get_ohlcv_from_file(
        self,
        path: Path,
        *,
        symbol: str,
        timeframe: str,
    ) -> pd.DataFrame:
        import json

        with open(path, encoding="utf-8") as f:
            raw = json.load(f)

        rows = raw.get("data", [])
        if not rows:
            raise DataProviderError(f"No data rows found in {path}")

        df = pd.DataFrame(rows)
        df = df.rename(columns={"time_key": OHLCVSchema.timestamp})
        return normalize_ohlcv(df, symbol=symbol, timeframe=timeframe)


@dataclass
class FutuLiveDataProvider:
    """从富途 OpenD 实时拉取 K 线数据。

    Usage::

        from futu import OpenQuoteContext
        ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
        provider = FutuLiveDataProvider()
        daily_df  = provider.get_daily(ctx, "US.AAPL")
        weekly_df = provider.get_weekly(ctx, "HK.00700")
        ctx.close()

    返回 DataFrame 经 ``normalize_ohlcv`` 标准化，列名遵循 ``OHLCVSchema``。
    """

    def get_kline(
        self,
        quote_ctx,
        code: str,
        kl_type,
        count: int,
        *,
        timeframe: str,
    ) -> pd.DataFrame:
        """通用 K 线拉取，通过 ``kl_type`` 指定周期。"""
        try:
            from futu import AuType  # type: ignore[import]
        except ImportError as exc:
            raise DataProviderError(
                "futu-api 未安装，请执行: pip install futu-api"
            ) from exc

        ret, df, _ = quote_ctx.request_history_kline(
            code,
            ktype=kl_type,
            autype=AuType.QFQ,
            max_count=count,
        )
        if ret != 0:
            raise DataProviderError(f"Futu API 拉取 {code} 失败: {df}")

        df = df.rename(columns={"time_key": OHLCVSchema.timestamp})
        return normalize_ohlcv(df, symbol=code, timeframe=timeframe)

    def get_daily(self, quote_ctx, code: str, count: int = 250) -> pd.DataFrame:
        """拉取日线 K 线（默认 250 根，满足 MA200 计算需求）。"""
        try:
            from futu import KLType  # type: ignore[import]
        except ImportError as exc:
            raise DataProviderError("futu-api 未安装") from exc
        return self.get_kline(quote_ctx, code, KLType.K_DAY, count, timeframe="1D")

    def get_weekly(self, quote_ctx, code: str, count: int = 60) -> pd.DataFrame:
        """拉取周线 K 线（默认 60 根，约 14 个月）。"""
        try:
            from futu import KLType  # type: ignore[import]
        except ImportError as exc:
            raise DataProviderError("futu-api 未安装") from exc
        return self.get_kline(quote_ctx, code, KLType.K_WEEK, count, timeframe="1W")


@dataclass
class ParquetDataProvider:
    schema: OHLCVSchema = OHLCVSchema()

    def get_ohlcv_from_file(
        self,
        path: Path,
        *,
        symbol: str,
        timeframe: str,
    ) -> pd.DataFrame:
        try:
            df = pd.read_parquet(path)
        except Exception as e:  # pragma: no cover
            raise DataProviderError(
                "Failed to read parquet. Install optional dependency: pip install -e '.[parquet]'"
            ) from e
        return normalize_ohlcv(df, symbol=symbol, timeframe=timeframe)
