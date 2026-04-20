"""API 服务层。

将存储层数据暴露为 HTTP 接口，供前端图表组件消费。
只做读取，不调用 Futu SDK，不做任何计算，可独立于后端运行。

启动：uvicorn trader_analysis.futu_strategy.api_server:app --host 0.0.0.0 --port 8000
文档：http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from trader_analysis.futu_strategy import storage

app = FastAPI(title="Strategy Indicators API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _ensure_db() -> None:
    storage.init_db()


@app.get("/api/indicators")
def get_indicators(
    code: str,
    ktype: str = Query(default="1d", pattern="^(1d|1w)$"),
    days: int = Query(default=60, ge=1, le=500),
):
    """返回某标的某周期最近 N 根 K 线 + 全部指标（日期升序，供图表使用）。"""
    rows = storage.query_range(code, ktype, days)
    return {"code": code, "ktype": ktype, "data": rows}


@app.get("/api/indicators/latest")
def get_latest(
    code: str,
    ktype: str = Query(default="1d", pattern="^(1d|1w)$"),
):
    """返回最新一根的所有指标值。"""
    return storage.query_latest(code, ktype)


@app.get("/api/scores/latest")
def get_latest_score(code: str):
    """返回最新一次评分结果。"""
    return storage.query_latest_score(code)


@app.get("/api/watchlist")
def get_watchlist():
    """返回所有已入库标的列表。"""
    return storage.list_codes()
