from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OHLCVSchema:
    timestamp: str = "timestamp"
    open: str = "open"
    high: str = "high"
    low: str = "low"
    close: str = "close"
    volume: str = "volume"
    symbol: str = "symbol"
    timeframe: str = "timeframe"


REQUIRED_OHLCV_COLUMNS = {
    OHLCVSchema.timestamp,
    OHLCVSchema.open,
    OHLCVSchema.high,
    OHLCVSchema.low,
    OHLCVSchema.close,
}
