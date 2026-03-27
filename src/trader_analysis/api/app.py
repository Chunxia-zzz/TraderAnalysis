from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

from trader_analysis.api.service import IndicatorService, ServiceConfig


def _cfg_from_env() -> ServiceConfig:
    data_path = Path(os.getenv("TA_DATA_PATH", "examples/sample_ohlcv.csv"))
    symbol = os.getenv("TA_SYMBOL", "DEMO")
    timeframe = os.getenv("TA_TIMEFRAME", "1D")
    strategy = os.getenv("TA_STRATEGY", "ma_cross")
    refresh_seconds = float(os.getenv("TA_REFRESH_SECONDS", "5"))
    return ServiceConfig(
        data_path=data_path,
        symbol=symbol,
        timeframe=timeframe,
        strategy=strategy,
        refresh_seconds=refresh_seconds,
    )


service = IndicatorService(_cfg_from_env())

@asynccontextmanager
async def lifespan(_app: FastAPI):
    await service.start()
    try:
        yield
    finally:
        await service.stop()


app = FastAPI(title="TraderAnalysis API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return await service.health()


@app.get("/v1/indicators/latest")
async def indicators_latest() -> dict:
    data = await service.latest_indicators()
    if not data:
        raise HTTPException(status_code=503, detail="No indicator data yet.")
    return data


@app.get("/v1/indicators/history")
async def indicators_history(limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    return await service.indicators_history(limit=limit)


@app.get("/v1/signals/latest")
async def signals_latest() -> dict:
    signal = await service.latest_signal()
    if signal is None:
        raise HTTPException(status_code=503, detail="No signal data yet.")
    return signal
