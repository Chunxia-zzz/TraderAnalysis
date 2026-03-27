from pathlib import Path

import pytest

from trader_analysis.api.service import IndicatorService, ServiceConfig


@pytest.mark.asyncio
async def test_refresh_once_produces_latest() -> None:
    svc = IndicatorService(
        ServiceConfig(
            data_path=Path("examples/sample_ohlcv.csv"),
            symbol="DEMO",
            timeframe="1D",
            strategy="ma_cross",
            refresh_seconds=1,
        )
    )
    await svc.refresh_once()
    latest = await svc.latest_indicators()
    signal = await svc.latest_signal()
    assert latest
    assert "close" in latest
    assert signal is not None
    assert "signal" in signal
