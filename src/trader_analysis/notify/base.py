from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from trader_analysis.signals.types import Signal


class Notifier(Protocol):
    def send(self, signals: list[Signal]) -> None:
        ...


@dataclass
class NoopNotifier:
    def send(self, signals: list[Signal]) -> None:
        _ = signals
