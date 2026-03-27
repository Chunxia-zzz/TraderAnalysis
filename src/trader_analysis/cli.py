from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd
import typer
import uvicorn

from trader_analysis.backtest.engine import BacktestConfig, run_backtest
from trader_analysis.data.providers import CSVDataProvider
from trader_analysis.strategy.examples import get_strategy

app = typer.Typer(add_completion=False, help="Quant indicators, signals, and backtest.")


@app.command()
def backtest(
    data: Path = typer.Option(..., exists=True, file_okay=True, dir_okay=False),
    strategy: str = typer.Option("ma_cross", help="Strategy name: ma_cross | rsi_reversal"),
    symbol: str = typer.Option("DEMO", help="Symbol identifier if the file has no symbol column."),
    timeframe: str = typer.Option("1D", help="Timeframe label (used for reporting)."),
    initial_cash: float = typer.Option(100000.0, help="Initial cash."),
    fee_bps: float = typer.Option(0.0, help="Fee in basis points per trade (round-turn simplified)."),
) -> None:
    provider = CSVDataProvider()
    df = provider.get_ohlcv_from_file(data, symbol=symbol, timeframe=timeframe)
    strat = get_strategy(strategy)

    cfg = BacktestConfig(initial_cash=initial_cash, fee_bps=fee_bps)
    result = run_backtest(df, strat, cfg)

    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2, default=str))


@app.command()
def signals(
    data: Path = typer.Option(..., exists=True, file_okay=True, dir_okay=False),
    strategy: str = typer.Option("ma_cross", help="Strategy name: ma_cross | rsi_reversal"),
    symbol: str = typer.Option("DEMO", help="Symbol identifier if the file has no symbol column."),
    timeframe: str = typer.Option("1D", help="Timeframe label (used for reporting)."),
    out: Optional[Path] = typer.Option(None, help="Write signals to CSV."),
) -> None:
    provider = CSVDataProvider()
    df = provider.get_ohlcv_from_file(data, symbol=symbol, timeframe=timeframe)
    strat = get_strategy(strategy)
    signals_df = strat.generate_signals(df).to_dataframe()

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        signals_df.to_csv(out, index=False)
        typer.echo(f"Wrote {len(signals_df)} signals to {out}")
    else:
        with pd.option_context("display.max_rows", 50, "display.width", 120):
            typer.echo(signals_df.tail(50).to_string(index=False))


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8000, help="Bind port."),
) -> None:
    uvicorn.run("trader_analysis.api.app:app", host=host, port=port, reload=False)

