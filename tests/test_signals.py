from pathlib import Path

from trader_analysis.data.providers import CSVDataProvider
from trader_analysis.strategy.examples import get_strategy


def test_strategy_outputs_signal_column() -> None:
    provider = CSVDataProvider()
    df = provider.get_ohlcv_from_file(Path("examples/sample_ohlcv.csv"), symbol="DEMO", timeframe="1D")
    strategy = get_strategy("ma_cross")
    signals_df = strategy.generate_signals(df).to_dataframe()
    assert "signal" in signals_df.columns
    assert len(signals_df) == len(df)
