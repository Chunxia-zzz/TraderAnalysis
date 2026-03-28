from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from trader_analysis.data.providers import CSVDataProvider, FutuJsonDataProvider
from trader_analysis.strategy.examples import get_strategy


@dataclass
class ServiceConfig:
    data_path: Path
    symbol: str = "DEMO"
    timeframe: str = "1D"
    strategy: str = "ma_cross"
    refresh_seconds: float = 5.0


class IndicatorService:
    def __init__(self, cfg: ServiceConfig) -> None:
        self.cfg = cfg
        self.provider = (
            FutuJsonDataProvider()
            if cfg.data_path.suffix == ".json"
            else CSVDataProvider()
        )
        self._lock = asyncio.Lock()
        self._history: list[dict[str, Any]] = []
        self._latest_signal: dict[str, Any] | None = None
        self._latest_refresh_ts: str | None = None
        self._runner_task: asyncio.Task[None] | None = None

    async def refresh_once(self) -> None:
        df = self.provider.get_ohlcv_from_file(
            self.cfg.data_path,
            symbol=self.cfg.symbol,
            timeframe=self.cfg.timeframe,
        )
        strategy = get_strategy(self.cfg.strategy)
        enriched = strategy.enrich(df)
        signals_df = strategy.generate_signals(df).to_dataframe()

        latest = enriched.iloc[-1].to_dict()
        latest_signal = signals_df.iloc[-1].to_dict() if not signals_df.empty else None

        for k, v in list(latest.items()):
            if isinstance(v, pd.Timestamp):
                latest[k] = v.isoformat()
            elif isinstance(v, (float, int)) and pd.isna(v):
                latest[k] = None
        if latest_signal is not None:
            for k, v in list(latest_signal.items()):
                if isinstance(v, pd.Timestamp):
                    latest_signal[k] = v.isoformat()

        history = enriched.tail(200).to_dict(orient="records")
        for row in history:
            for k, v in list(row.items()):
                if isinstance(v, pd.Timestamp):
                    row[k] = v.isoformat()
                elif isinstance(v, (float, int)) and pd.isna(v):
                    row[k] = None

        async with self._lock:
            self._history = history
            self._latest_signal = latest_signal
            self._latest_refresh_ts = pd.Timestamp.now(tz="UTC").isoformat()

    async def start(self) -> None:
        await self.refresh_once()

        async def _loop() -> None:
            while True:
                try:
                    await self.refresh_once()
                except Exception:
                    # Keep loop alive; caller can inspect health endpoint.
                    pass
                await asyncio.sleep(self.cfg.refresh_seconds)

        self._runner_task = asyncio.create_task(_loop())

    async def stop(self) -> None:
        if self._runner_task is not None:
            self._runner_task.cancel()
            try:
                await self._runner_task
            except asyncio.CancelledError:
                pass

    async def latest_indicators(self) -> dict[str, Any]:
        async with self._lock:
            if not self._history:
                return {}
            return self._history[-1]

    async def indicators_history(self, limit: int) -> list[dict[str, Any]]:
        async with self._lock:
            return self._history[-limit:]

    async def latest_signal(self) -> dict[str, Any] | None:
        async with self._lock:
            return self._latest_signal

    async def health(self) -> dict[str, Any]:
        async with self._lock:
            return {
                "status": "ok",
                "last_refresh_utc": self._latest_refresh_ts,
                "history_size": len(self._history),
                "strategy": self.cfg.strategy,
                "symbol": self.cfg.symbol,
                "timeframe": self.cfg.timeframe,
                "refresh_seconds": self.cfg.refresh_seconds,
                "data_path": str(self.cfg.data_path),
            }
