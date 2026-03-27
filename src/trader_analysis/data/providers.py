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
