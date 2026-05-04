"""API 服务层。

将存储层数据暴露为 HTTP 接口，供前端图表组件消费。
只做读取，不调用 Futu SDK，不做任何计算，可独立于后端运行。

启动：uvicorn trader_analysis.futu_strategy.api_server:app --host 0.0.0.0 --port 8000
文档：http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from trader_analysis.futu_strategy import config, storage

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


@app.get("/health")
def health_check():
    """健康检查，前端启动时调用以检测后端是否在线。"""
    return {"status": "ok"}


@app.get("/api/indicators")
def get_indicators(
    code: str,
    ktype: str = Query(default="1d", pattern="^(1d|1w)$"),
    days: int = Query(default=60, ge=1, le=500),
):
    """返回某标的某周期最近 N 根 K 线 + 全部指标（日期升序，供图表使用）。"""
    rows = storage.query_range(code, ktype, days)
    if not rows:
        ktype_label = {"1d": "日线", "1w": "周线"}.get(ktype, ktype)
        return JSONResponse(
            status_code=404,
            content={
                "code": code,
                "ktype": ktype,
                "data": [],
                "message": f"{code} 暂无{ktype_label}数据，请等待历史数据导入完成",
            },
        )
    return {"code": code, "ktype": ktype, "data": rows}


@app.get("/api/indicators/latest")
def get_latest(
    code: str,
    ktype: str = Query(default="1d", pattern="^(1d|1w)$"),
):
    """返回最新一根的所有指标值。"""
    result = storage.query_latest(code, ktype)
    if not result:
        return JSONResponse(
            status_code=404,
            content={
                "message": f"{code} 暂无数据，请等待历史数据导入完成",
            },
        )
    return result


@app.get("/api/scores/latest")
def get_latest_score(code: str):
    """返回最新一次评分结果。"""
    result = storage.query_latest_score(code)
    if not result:
        return JSONResponse(
            status_code=404,
            content={
                "message": f"{code} 暂无评分数据",
            },
        )
    return result


@app.get("/api/watchlist")
def get_watchlist():
    """返回完整标的池（含名称、分类、标签等元信息），数据来源为 watchlist.json。"""
    codes_in_db = set(storage.list_codes())
    items = []
    for item in config.WATCHLIST_DETAIL:
        items.append({
            **item,
            "has_data": item["futu_code"] in codes_in_db,
        })
    return {
        "categories": config.WATCHLIST_CATEGORIES,
        "watchlist": items,
    }


@app.get("/api/market-temperature")
def get_market_temperature():
    """返回最新一期市场温度评分，供前端仪表盘展示。"""
    result = storage.query_latest_market_score()
    if not result:
        return JSONResponse(
            status_code=404,
            content={"message": "暂无市场温度数据，请先运行 trader-analysis temperature 命令"},
        )
    return result


@app.get("/api/market-temperature/history")
def get_market_temperature_history(
    days: int = Query(default=30, ge=1, le=365),
):
    """返回近 N 天的市场温度评分历史，用于趋势图。"""
    history = storage.query_market_score_history(days)
    return {"history": history}
