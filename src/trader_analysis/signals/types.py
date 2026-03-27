from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable

import pandas as pd


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class Signal:
    timestamp: pd.Timestamp
    symbol: str
    signal: SignalType
    strength: float = 1.0
    reason: str = ""


@dataclass
class SignalSet:
    items: list[Signal]

    @classmethod
    def from_iterable(cls, items: Iterable[Signal]) -> "SignalSet":
        return cls(list(items))

    def to_dataframe(self) -> pd.DataFrame:
        rows = [asdict(s) for s in self.items]
        df = pd.DataFrame(rows)
        if not df.empty:
            df["signal"] = df["signal"].astype(str).str.replace("SignalType.", "", regex=False)
        return df
