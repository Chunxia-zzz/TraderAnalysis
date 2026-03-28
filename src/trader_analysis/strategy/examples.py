from __future__ import annotations

from trader_analysis.indicators.builtins import _sma_spec, rsi
from trader_analysis.signals.rules import MovingAverageCrossRule, RSIReversalRule
from trader_analysis.strategy.strategy import Strategy


def ma_cross_strategy() -> Strategy:
    fast = "sma_5"
    slow = "sma_20"
    return Strategy(
        name="ma_cross",
        indicators=[_sma_spec(5, out_col=fast), _sma_spec(20, out_col=slow)],
        rule=MovingAverageCrossRule(fast_col=fast, slow_col=slow),
    )


def rsi_reversal_strategy() -> Strategy:
    rsi_col = "rsi_14"
    return Strategy(
        name="rsi_reversal",
        indicators=[rsi(14, out_col=rsi_col)],
        rule=RSIReversalRule(rsi_col=rsi_col, buy_threshold=30.0, sell_threshold=70.0),
    )


def get_strategy(name: str) -> Strategy:
    mapping = {
        "ma_cross": ma_cross_strategy,
        "rsi_reversal": rsi_reversal_strategy,
    }
    try:
        return mapping[name]()
    except KeyError as e:
        raise ValueError(f"Unknown strategy: {name}. Available: {sorted(mapping)}") from e
