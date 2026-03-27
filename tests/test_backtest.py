from pathlib import Path

from trader_analysis.backtest.engine import BacktestConfig, run_backtest
from trader_analysis.data.providers import CSVDataProvider
from trader_analysis.strategy.examples import get_strategy


def test_backtest_returns_summary() -> None:
    provider = CSVDataProvider()
    df = provider.get_ohlcv_from_file(Path("examples/sample_ohlcv.csv"), symbol="DEMO", timeframe="1D")
    strategy = get_strategy("rsi_reversal")
    result = run_backtest(df, strategy, BacktestConfig(initial_cash=10000))
    assert "total_return" in result.summary
    assert "max_drawdown" in result.summary
