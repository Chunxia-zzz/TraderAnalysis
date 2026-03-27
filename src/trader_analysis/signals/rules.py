from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trader_analysis.data.schemas import OHLCVSchema
from trader_analysis.signals.types import Signal, SignalSet, SignalType


def _cross_up(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))


def _cross_down(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a < b) & (a.shift(1) >= b.shift(1))


@dataclass
class SignalRule:
    name: str

    def evaluate(self, df: pd.DataFrame) -> SignalSet:
        raise NotImplementedError


@dataclass
class MovingAverageCrossRule(SignalRule):
    fast_col: str
    slow_col: str

    def __init__(self, fast_col: str, slow_col: str) -> None:
        super().__init__(name="ma_cross")
        self.fast_col = fast_col
        self.slow_col = slow_col

    def evaluate(self, df: pd.DataFrame) -> SignalSet:
        buy = _cross_up(df[self.fast_col], df[self.slow_col])
        sell = _cross_down(df[self.fast_col], df[self.slow_col])

        signals: list[Signal] = []
        for i, row in df.iterrows():
            st = SignalType.HOLD
            reason = "no crossover"
            if bool(buy.iloc[i]):
                st = SignalType.BUY
                reason = f"{self.fast_col} crossed above {self.slow_col}"
            elif bool(sell.iloc[i]):
                st = SignalType.SELL
                reason = f"{self.fast_col} crossed below {self.slow_col}"
            signals.append(
                Signal(
                    timestamp=pd.Timestamp(row[OHLCVSchema.timestamp]),
                    symbol=str(row.get(OHLCVSchema.symbol, "UNKNOWN")),
                    signal=st,
                    reason=reason,
                )
            )
        return SignalSet(signals)


@dataclass
class RSIReversalRule(SignalRule):
    rsi_col: str
    buy_threshold: float = 30.0
    sell_threshold: float = 70.0

    def __init__(self, rsi_col: str, buy_threshold: float = 30.0, sell_threshold: float = 70.0) -> None:
        super().__init__(name="rsi_reversal")
        self.rsi_col = rsi_col
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    def evaluate(self, df: pd.DataFrame) -> SignalSet:
        rsi = df[self.rsi_col]
        buy = (rsi > self.buy_threshold) & (rsi.shift(1) <= self.buy_threshold)
        sell = (rsi < self.sell_threshold) & (rsi.shift(1) >= self.sell_threshold)

        signals: list[Signal] = []
        for i, row in df.iterrows():
            st = SignalType.HOLD
            reason = "rsi neutral"
            if bool(buy.iloc[i]):
                st = SignalType.BUY
                reason = f"{self.rsi_col} crossed above {self.buy_threshold}"
            elif bool(sell.iloc[i]):
                st = SignalType.SELL
                reason = f"{self.rsi_col} crossed below {self.sell_threshold}"
            signals.append(
                Signal(
                    timestamp=pd.Timestamp(row[OHLCVSchema.timestamp]),
                    symbol=str(row.get(OHLCVSchema.symbol, "UNKNOWN")),
                    signal=st,
                    reason=reason,
                )
            )
        return SignalSet(signals)
