from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from trader_analysis.indicators.base import IndicatorSpec, apply_indicators
from trader_analysis.signals.rules import SignalRule
from trader_analysis.signals.types import SignalSet


@dataclass
class Strategy:
    name: str
    indicators: list[IndicatorSpec]
    rule: SignalRule

    def enrich(self, df: pd.DataFrame) -> pd.DataFrame:
        return apply_indicators(df, self.indicators)

    def generate_signals(self, df: pd.DataFrame) -> SignalSet:
        enriched = self.enrich(df)
        return self.rule.evaluate(enriched)
