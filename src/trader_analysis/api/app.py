from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.responses import HTMLResponse

from trader_analysis.api.service import IndicatorService, ServiceConfig

# Bootcdn mirrors — accessible in mainland China
_SWAGGER_JS  = "https://cdn.bootcdn.net/ajax/libs/swagger-ui/5.11.0/swagger-ui-bundle.js"
_SWAGGER_CSS = "https://cdn.bootcdn.net/ajax/libs/swagger-ui/5.11.0/swagger-ui.css"
_REDOC_JS    = "https://cdn.bootcdn.net/ajax/libs/redoc/2.1.3/bundles/redoc.standalone.js"


def _cfg_from_env() -> ServiceConfig:
    data_path = Path(os.getenv("TA_DATA_PATH", "examples/mock_futu_kline_HK.00700.json"))
    symbol = os.getenv("TA_SYMBOL", "HK.00700")
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


app = FastAPI(
    title="TraderAnalysis API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,   # disable default /docs (uses jsdelivr CDN)
    redoc_url=None,  # disable default /redoc
)


@app.get("/docs", include_in_schema=False)
async def swagger_ui() -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="TraderAnalysis API",
        swagger_js_url=_SWAGGER_JS,
        swagger_css_url=_SWAGGER_CSS,
    )


@app.get("/redoc", include_in_schema=False)
async def redoc_ui() -> HTMLResponse:
    return get_redoc_html(
        openapi_url="/openapi.json",
        title="TraderAnalysis API",
        redoc_js_url=_REDOC_JS,
    )


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
