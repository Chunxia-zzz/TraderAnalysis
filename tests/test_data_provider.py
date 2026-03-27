from pathlib import Path

from trader_analysis.data.providers import CSVDataProvider


def test_csv_provider_normalizes_schema() -> None:
    provider = CSVDataProvider()
    df = provider.get_ohlcv_from_file(
        Path("examples/sample_ohlcv.csv"),
        symbol="DEMO",
        timeframe="1D",
    )
    assert {"timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"} <= set(df.columns)
    assert len(df) > 0
