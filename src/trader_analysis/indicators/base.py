from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Mapping, MutableMapping

import pandas as pd


IndicatorFn = Callable[[pd.DataFrame], pd.DataFrame]


@dataclass(frozen=True)
class IndicatorSpec:
    name: str
    fn: IndicatorFn
    outputs: tuple[str, ...]


class IndicatorRegistry:
    def __init__(self) -> None:
        self._items: MutableMapping[str, IndicatorSpec] = {}

    def register(self, spec: IndicatorSpec) -> None:
        if spec.name in self._items:
            raise ValueError(f"Indicator already registered: {spec.name}")
        self._items[spec.name] = spec

    def get(self, name: str) -> IndicatorSpec:
        try:
            return self._items[name]
        except KeyError as e:
            raise KeyError(f"Unknown indicator: {name}. Available: {sorted(self._items)}") from e

    def list(self) -> list[str]:
        return sorted(self._items.keys())


def apply_indicators(df: pd.DataFrame, specs: Iterable[IndicatorSpec]) -> pd.DataFrame:
    out = df.copy()
    for spec in specs:
        result = spec.fn(out)
        for col in spec.outputs:
            if col not in result.columns:
                raise ValueError(f"Indicator {spec.name} did not produce column {col}")
        out = result
    return out
