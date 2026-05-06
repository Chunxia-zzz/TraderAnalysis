"""API 服务层。

将存储层数据暴露为 HTTP 接口，供前端图表组件消费。
只做读取，不调用 Futu SDK，不做任何计算，可独立于后端运行。

启动：uvicorn trader_analysis.futu_strategy.api_server:app --host 0.0.0.0 --port 8000
文档：http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from trader_analysis.futu_strategy import auth_storage, config, storage, watchlist_storage
from trader_analysis.futu_strategy.auth import (
    ChangePasswordRequest,
    LoginRequest,
    create_access_token,
    get_current_user,
    hash_password,
    require_admin,
    verify_password,
)
from trader_analysis.futu_strategy.stock_info_fetcher import (
    OpenDNotConnected,
    fetch_stock_info,
    search_stocks,
)

app = FastAPI(title="Strategy Indicators API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _ensure_db() -> None:
    storage.init_db()
    auth_storage.init_users_table()
    watchlist_storage.init_watchlist_table()


# ── 公开端点 ──────────────────────────────────────────────────────────────────


@app.get("/health")
def health_check():
    """健康检查，前端启动时调用以检测后端是否在线。"""
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(body: LoginRequest):
    """用户登录，返回 JWT。"""
    user = auth_storage.query_user_by_username(body.username)
    if user is None or not verify_password(body.password, user["password_hash"]):
        return {"data": None, "message": "Invalid username or password"}

    token = create_access_token(user["username"], user["role"])
    auth_storage.update_last_login(user["username"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": config.JWT_EXPIRE_DAYS * 86400,
        "role": user["role"],
    }


# ── 需要认证的端点 ────────────────────────────────────────────────────────────


@app.get("/api/auth/me")
def get_me(user: dict = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "created_at": user["created_at"],
        "last_login": user["last_login"],
    }


@app.post("/api/auth/change-password")
def change_password(body: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    """修改当前用户密码。"""
    if not verify_password(body.old_password, user["password_hash"]):
        return {"data": None, "message": "Old password is incorrect"}
    new_hash = hash_password(body.new_password)
    auth_storage.update_password(user["username"], new_hash)
    return {"message": "Password updated"}


@app.get("/api/indicators")
def get_indicators(
    code: str,
    ktype: str = Query(default="1d", pattern="^(1d|1w)$"),
    days: int = Query(default=60, ge=1, le=500),
    user: dict = Depends(get_current_user),
):
    """返回某标的某周期最近 N 根 K 线 + 全部指标（日期升序，供图表使用）。"""
    rows = storage.query_range(code, ktype, days)
    if not rows:
        ktype_label = {"1d": "日线", "1w": "周线"}.get(ktype, ktype)
        return {
            "code": code,
            "ktype": ktype,
            "data": [],
            "message": f"{code} 暂无{ktype_label}数据，请等待历史数据导入完成",
        }
    return {"code": code, "ktype": ktype, "data": rows}


@app.get("/api/indicators/latest")
def get_latest(
    code: str,
    ktype: str = Query(default="1d", pattern="^(1d|1w)$"),
    user: dict = Depends(get_current_user),
):
    """返回最新一根的所有指标值。"""
    result = storage.query_latest(code, ktype)
    if not result:
        return {"data": None, "message": f"{code} 暂无数据，请等待历史数据导入完成"}
    return result


@app.get("/api/scores/latest")
def get_latest_score(
    code: str,
    date: str | None = Query(default=None, description="指定日期 YYYY-MM-DD，不传则返回最新"),
    user: dict = Depends(get_current_user),
):
    """返回评分结果。支持查询指定日期的历史评分。"""
    if date is not None:
        result = storage.query_score_by_date(code, date)
        if not result:
            return {"data": None, "message": f"{code} 在 {date} 暂无评分数据（可能为非交易日）"}
    else:
        result = storage.query_latest_score(code)
        if not result:
            return {"data": None, "message": f"{code} 暂无评分数据"}
    return result


@app.get("/api/watchlist")
def get_watchlist(
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    market: str | None = Query(default=None),
    search: str | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """返回标的池（支持筛选）。数据来源为 SQLite watchlist 表。"""
    items = watchlist_storage.list_watchlist(category, status, market, search)
    codes_in_db = set(storage.list_codes())
    for item in items:
        item["has_data"] = item["code"] in codes_in_db
    return {
        "total": len(items),
        "categories": config.WATCHLIST_CATEGORIES,
        "watchlist": items,
    }


@app.get("/api/watchlist/{code}")
def get_watchlist_item(code: str, user: dict = Depends(get_current_user)):
    """查询单只标的详情。"""
    item = watchlist_storage.get_stock(code)
    if not item:
        return {"data": None, "message": f"Stock {code} not found in watchlist"}
    codes_in_db = set(storage.list_codes())
    item["has_data"] = item["code"] in codes_in_db
    return item


class WatchlistAddRequest(BaseModel):
    code: str
    category: str = ""
    thesis: str = ""
    notes: str = ""
    tags: list[str] = []
    target_price: float | None = None
    stop_loss: float | None = None


@app.post("/api/watchlist", status_code=201)
def add_watchlist_item(body: WatchlistAddRequest, user: dict = Depends(require_admin)):
    """新增标的。自动从富途获取基础信息填充。"""
    existing = watchlist_storage.get_stock(body.code)
    if existing:
        return {"data": None, "message": f"Stock {body.code} already exists in watchlist"}

    # 尝试从富途获取基础信息
    futu_info = fetch_stock_info(body.code)

    data = body.model_dump()
    if futu_info:
        data.update({k: v for k, v in futu_info.items() if v is not None})

    record = watchlist_storage.add_stock(data)
    return {"message": f"Stock {body.code} added to watchlist", "data": record}


@app.patch("/api/watchlist/{code}")
def update_watchlist_item(code: str, body: dict, user: dict = Depends(require_admin)):
    """修改标的可编辑字段（部分更新）。"""
    existing = watchlist_storage.get_stock(code)
    if not existing:
        return {"data": None, "message": f"Stock {code} not found in watchlist"}

    result, updated_or_violations = watchlist_storage.update_stock(code, body)
    if result is None:
        # readonly violation
        return {"data": None, "message": f"Fields not editable: {', '.join(updated_or_violations)}"}

    return {
        "message": f"Stock {code} updated",
        "data": result,
        "updated_fields": updated_or_violations,
    }


@app.delete("/api/watchlist/{code}")
def delete_watchlist_item(code: str, user: dict = Depends(require_admin)):
    """删除标的（仅从 watchlist 移除，不删历史数据）。"""
    watchlist_storage.delete_stock(code)
    return {"message": f"Stock {code} removed from watchlist"}


class WatchlistBatchRequest(BaseModel):
    codes: list[str]
    category: str = ""
    tags: list[str] = []


@app.post("/api/watchlist/batch")
def batch_add_watchlist(body: WatchlistBatchRequest, user: dict = Depends(require_admin)):
    """批量新增标的。"""
    defaults = {"category": body.category, "tags": body.tags}
    added, skipped = watchlist_storage.batch_add(body.codes, defaults)
    return {
        "message": f"{len(added)} stocks added, {len(skipped)} skipped",
        "added": added,
        "skipped": skipped,
    }


@app.post("/api/watchlist/refresh-snapshot")
def refresh_watchlist_snapshot(
    code: str | None = Query(default=None),
    user: dict = Depends(require_admin),
):
    """刷新标的静态快照字段（trailing_pe, market_cap 等）。"""
    from trader_analysis.futu_strategy.stock_info_fetcher import fetch_snapshot_batch

    if code:
        codes = [code]
    else:
        codes = watchlist_storage.get_all_codes()

    snapshots = fetch_snapshot_batch(codes)
    updated = 0
    failed = []
    for c in codes:
        if c in snapshots:
            watchlist_storage.refresh_snapshot(c, snapshots[c])
            updated += 1
        else:
            failed.append(c)

    return {"message": f"Refreshed {updated} stocks", "updated": updated, "failed": failed}


# ── 选股接口 ──────────────────────────────────────────────────────────────────


@app.get("/api/stock-filter/search")
def stock_filter_search(
    market: str = Query(default="US"),
    min_market_cap: float | None = Query(default=None, description="最小市值（亿美元）"),
    max_pe: float | None = Query(default=None),
    min_price: float | None = Query(default=None),
    sector: str | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """条件选股（需 OpenD 在线）。"""
    try:
        results = search_stocks(market, min_market_cap, max_pe, min_price, sector)
    except OpenDNotConnected:
        return {"data": None, "message": "Futu OpenD not connected"}

    # 标记是否已在 watchlist
    existing_codes = set(watchlist_storage.get_all_codes(exclude_exited=False))
    for r in results:
        r["in_watchlist"] = r["code"] in existing_codes

    return {"total": len(results), "results": results}


@app.get("/api/stock-filter/info")
def stock_filter_info(
    code: str = Query(...),
    user: dict = Depends(get_current_user),
):
    """查询单股基础信息（用于新增前预览）。"""
    info = fetch_stock_info(code)
    if info is None:
        return {"data": None, "message": "Futu OpenD not connected or stock not found"}

    parts = code.split(".", 1)
    return {
        "code": code,
        "ticker": parts[1] if len(parts) == 2 else code,
        "market": parts[0] if len(parts) == 2 else "US",
        **info,
    }


@app.get("/api/scores/overview")
def get_scores_overview(
    date: str | None = Query(default=None, description="指定日期 YYYY-MM-DD，不传则取各标的最新评分"),
    user: dict = Depends(get_current_user),
):
    """返回所有标的的评分概览，按分数降序，按信号分组。用于速览买入机会。"""
    rows = storage.query_scores_overview(date)
    if not rows:
        msg = "暂无评分数据" if not date else f"{date} 暂无评分数据（可能为非交易日）"
        return {"data": None, "message": msg}

    # 按信号分组
    strong_buy = [r for r in rows if r["signal"] == "STRONG_BUY"]
    buy = [r for r in rows if r["signal"] == "BUY"]
    no_action = [r for r in rows if r["signal"] == "NO_ACTION"]

    return {
        "date": date or (rows[0]["date"] if rows else None),
        "total_count": len(rows),
        "strong_buy": strong_buy,
        "buy": buy,
        "no_action": no_action,
        "summary": {
            "strong_buy_count": len(strong_buy),
            "buy_count": len(buy),
            "no_action_count": len(no_action),
        },
    }


# ── 基本面接口 ────────────────────────────────────────────────────────────────


@app.get("/api/fundamental/latest")
def get_fundamental_latest(
    code: str = Query(...),
    user: dict = Depends(get_current_user),
):
    """返回某标的最新基本面分析数据。"""
    result = storage.query_latest_fundamental(code)
    if not result:
        return {"data": None, "message": f"{code} 暂无基本面数据，请先运行 trader-analysis fundamental"}
    # 结构化响应
    return {
        "code": result["code"],
        "date": result["date"],
        "current_price": result.get("current_price"),
        "valuation": {
            "trailing_pe": result.get("trailing_pe"),
            "forward_pe": result.get("forward_pe"),
            "trailing_eps": result.get("trailing_eps"),
            "forward_eps": result.get("forward_eps"),
            "peg_ratio": result.get("peg_ratio"),
            "price_to_book": result.get("price_to_book"),
            "ev_to_ebitda": result.get("ev_to_ebitda"),
        },
        "growth": {
            "revenue_growth": result.get("revenue_growth"),
            "earnings_growth": result.get("earnings_growth"),
        },
        "analyst": {
            "target_mean": result.get("target_mean"),
            "target_median": result.get("target_median"),
            "target_high": result.get("target_high"),
            "target_low": result.get("target_low"),
            "analyst_count": result.get("analyst_count"),
            "recommendation": result.get("recommendation"),
        },
        "financial_health": {
            "roe": result.get("roe"),
            "profit_margin": result.get("profit_margin"),
            "gross_margin": result.get("gross_margin"),
            "debt_to_equity": result.get("debt_to_equity"),
            "free_cashflow": result.get("free_cashflow"),
            "current_ratio": result.get("current_ratio"),
        },
        "score": {
            "fundamental_score": result.get("fundamental_score"),
            "valuation_signal": result.get("valuation_signal"),
            "breakdown": result.get("breakdown", {}),
        },
        "updated_at": result.get("updated_at"),
    }


@app.get("/api/fundamental/overview")
def get_fundamental_overview(user: dict = Depends(get_current_user)):
    """全标的基本面速览，按评分降序分组。"""
    rows = storage.query_fundamentals_overview()
    if not rows:
        return {"data": None, "message": "暂无基本面数据，请先运行 trader-analysis fundamental"}

    undervalued = [r for r in rows if r.get("valuation_signal") == "UNDERVALUED"]
    fair = [r for r in rows if r.get("valuation_signal") == "FAIR"]
    overvalued = [r for r in rows if r.get("valuation_signal") == "OVERVALUED"]

    # 跳过的 ETF/杠杆产品
    from trader_analysis.futu_strategy.config import FUNDAMENTAL_SKIP_TICKERS, get_watchlist
    all_codes = get_watchlist()
    scored_codes = {r["code"] for r in rows}
    skipped = [c for c in all_codes if c not in scored_codes]

    return {
        "date": rows[0]["date"] if rows else None,
        "total_count": len(rows),
        "undervalued": undervalued,
        "fair": fair,
        "overvalued": overvalued,
        "skipped": skipped,
        "summary": {
            "undervalued_count": len(undervalued),
            "fair_count": len(fair),
            "overvalued_count": len(overvalued),
            "skipped_count": len(skipped),
        },
    }


@app.get("/api/market-temperature")
def get_market_temperature(user: dict = Depends(get_current_user)):
    """返回最新一期市场温度评分，供前端仪表盘展示。"""
    result = storage.query_latest_market_score()
    if not result:
        return {"data": None, "message": "暂无市场温度数据，请先运行 trader-analysis temperature 命令"}
    return result


@app.get("/api/market-temperature/history")
def get_market_temperature_history(
    days: int = Query(default=30, ge=1, le=365),
    user: dict = Depends(get_current_user),
):
    """返回近 N 天的市场温度评分历史，用于趋势图。"""
    history = storage.query_market_score_history(days)
    return {"history": history}
