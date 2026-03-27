from __future__ import annotations

import numpy as np
import pandas as pd


def max_drawdown(equity_curve: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    peak = equity_curve.cummax()
    dd = (equity_curve / peak) - 1.0
    return float(dd.min())


def win_rate(trade_returns: list[float]) -> float:
    if not trade_returns:
        return 0.0
    wins = sum(1 for r in trade_returns if r > 0)
    return wins / len(trade_returns)


def annualized_sharpe(daily_returns: pd.Series, periods_per_year: int = 252) -> float:
    if daily_returns.empty:
        return 0.0
    std = float(daily_returns.std(ddof=0))
    if std == 0.0:
        return 0.0
    mean = float(daily_returns.mean())
    return float((mean / std) * np.sqrt(periods_per_year))
