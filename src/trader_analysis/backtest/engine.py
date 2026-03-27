from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trader_analysis.backtest.report import annualized_sharpe, max_drawdown, win_rate
from trader_analysis.data.schemas import OHLCVSchema
from trader_analysis.signals.types import SignalType
from trader_analysis.strategy.strategy import Strategy


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 100000.0
    fee_bps: float = 0.0


@dataclass
class BacktestResult:
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    summary: dict[str, float | int | str]


def run_backtest(df: pd.DataFrame, strategy: Strategy, cfg: BacktestConfig) -> BacktestResult:
    enriched = strategy.enrich(df)
    signals_df = strategy.generate_signals(df).to_dataframe()
    signal_map = dict(zip(signals_df["timestamp"], signals_df["signal"]))

    cash = cfg.initial_cash
    position_qty = 0.0
    position_entry = 0.0

    equities: list[dict] = []
    trades: list[dict] = []
    trade_returns: list[float] = []

    for _, row in enriched.iterrows():
        ts = pd.Timestamp(row[OHLCVSchema.timestamp])
        px = float(row[OHLCVSchema.close])
        sig = signal_map.get(ts, "HOLD")

        if sig == SignalType.BUY.value and position_qty == 0.0 and px > 0:
            fee = cash * (cfg.fee_bps / 10000.0)
            investable = max(cash - fee, 0.0)
            position_qty = investable / px if px else 0.0
            cash = 0.0
            position_entry = px
            trades.append({"timestamp": ts, "side": "BUY", "price": px, "qty": position_qty, "fee": fee})
        elif sig == SignalType.SELL.value and position_qty > 0.0:
            gross = position_qty * px
            fee = gross * (cfg.fee_bps / 10000.0)
            cash = gross - fee
            r = (px / position_entry) - 1.0 if position_entry > 0 else 0.0
            trade_returns.append(r)
            trades.append({"timestamp": ts, "side": "SELL", "price": px, "qty": position_qty, "fee": fee})
            position_qty = 0.0
            position_entry = 0.0

        equity = cash + position_qty * px
        equities.append({"timestamp": ts, "equity": equity, "close": px, "signal": sig})

    equity_df = pd.DataFrame(equities)
    trade_df = pd.DataFrame(trades)

    total_return = 0.0
    if not equity_df.empty:
        total_return = float((equity_df["equity"].iloc[-1] / cfg.initial_cash) - 1.0)

    daily_returns = equity_df["equity"].pct_change().dropna() if not equity_df.empty else pd.Series(dtype=float)
    buy_count = int((signals_df["signal"] == "BUY").sum()) if not signals_df.empty else 0
    sell_count = int((signals_df["signal"] == "SELL").sum()) if not signals_df.empty else 0
    hold_count = int((signals_df["signal"] == "HOLD").sum()) if not signals_df.empty else 0

    summary = {
        "strategy": strategy.name,
        "initial_cash": cfg.initial_cash,
        "final_equity": float(equity_df["equity"].iloc[-1]) if not equity_df.empty else cfg.initial_cash,
        "total_return": total_return,
        "max_drawdown": max_drawdown(equity_df["equity"]) if not equity_df.empty else 0.0,
        "sharpe": annualized_sharpe(daily_returns),
        "trade_count": int(len(trade_df) // 2),
        "win_rate": win_rate(trade_returns),
        "signal_buy_count": buy_count,
        "signal_sell_count": sell_count,
        "signal_hold_count": hold_count,
    }

    return BacktestResult(equity_curve=equity_df, trades=trade_df, summary=summary)
