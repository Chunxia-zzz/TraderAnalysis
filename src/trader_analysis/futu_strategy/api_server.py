"""API 服务层。

将存储层数据暴露为 HTTP 接口，供前端图表组件消费。
只做读取，不调用 Futu SDK，不做任何计算，可独立于后端运行。

启动：uvicorn trader_analysis.futu_strategy.api_server:app --host 0.0.0.0 --port 8000
文档：http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from trader_analysis.futu_strategy import config, storage, watchlist_storage

# AUTH DISABLED: 认证模块暂时禁用，所有接口无需登录即可访问
# from trader_analysis.futu_strategy import auth_storage
# from trader_analysis.futu_strategy.auth import (
#     ChangePasswordRequest,
#     LoginRequest,
#     create_access_token,
#     get_current_user,
#     hash_password,
#     require_admin,
#     verify_password,
# )
# stock_info_fetcher: 仅保留 fetch_stock_info 供 watchlist 新增时获取基础信息
from trader_analysis.futu_strategy.stock_info_fetcher import (
    fetch_stock_info,
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
    # auth_storage.init_users_table()  # AUTH DISABLED
    watchlist_storage.init_watchlist_table()


# ── 公开端点 ──────────────────────────────────────────────────────────────────


@app.get("/health")
def health_check():
    """健康检查，前端启动时调用以检测后端是否在线。"""
    return {"status": "ok"}


# AUTH DISABLED: 登录/用户信息/修改密码端点暂时禁用
# @app.post("/api/auth/login")
# def login(body: LoginRequest):
#     ...
#
# @app.get("/api/auth/me")
# def get_me(user: dict = Depends(get_current_user)):
#     ...
#
# @app.post("/api/auth/change-password")
# def change_password(body: ChangePasswordRequest, user: dict = Depends(get_current_user)):
#     ...


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
def get_watchlist_item(code: str):
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
def add_watchlist_item(body: WatchlistAddRequest):
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
def update_watchlist_item(code: str, body: dict):
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
def delete_watchlist_item(code: str):
    """删除标的（仅从 watchlist 移除，不删历史数据）。"""
    watchlist_storage.delete_stock(code)
    return {"message": f"Stock {code} removed from watchlist"}


class WatchlistBatchRequest(BaseModel):
    codes: list[str]
    category: str = ""
    tags: list[str] = []


@app.post("/api/watchlist/batch")
def batch_add_watchlist(body: WatchlistBatchRequest):
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


# ── 选股接口（已禁用）─────────────────────────────────────────────────────────
# 条件选股功能已移除：标的池已手动筛选龙头，新增标的通过 POST /api/watchlist 即可。
# @app.get("/api/stock-filter/search")
# @app.get("/api/stock-filter/info")


def _calc_momentum(kline_rows: list) -> int:
    """计算动量/趋势强度评分 (0-100)。用于识别主升浪标的。

    5 维度：均线排列(25) + RSI强势(20) + MACD方向(20) + 20日涨幅(20) + 量能(15)
    """
    if not kline_rows:
        return 0
    r = kline_rows[0]
    close = float(r["close"]) if r["close"] else 0
    ma5 = float(r["ma5"]) if r["ma5"] else None
    ma10 = float(r["ma10"]) if r["ma10"] else None
    ma20 = float(r["ma20"]) if r["ma20"] else None
    ma60 = float(r["ma60"]) if r["ma60"] else None
    rsi = float(r["rsi6"]) if r["rsi6"] else 50
    dif = float(r["dif"]) if r["dif"] else 0
    dea = float(r["dea"]) if r["dea"] else 0
    macd = float(r["macd"]) if r["macd"] else 0
    vol = float(r["volume"]) if r["volume"] else 0
    vol_ma = float(r["vol_ma20"]) if r["vol_ma20"] else 1

    score = 0

    # 1. 均线多头排列 (0-25)
    if all([ma5, ma10, ma20, ma60]):
        if ma5 > ma10 > ma20 > ma60:
            score += 25
        elif ma5 > ma10 > ma20:
            score += 15
        elif ma5 > ma10:
            score += 8

    # 2. RSI 强势区 (0-20): 50-90 给分
    if 50 <= rsi <= 80:
        score += round((rsi - 50) / 30 * 20)
    elif 80 < rsi <= 90:
        score += 20
    elif rsi > 90:
        score += 15  # 过热稍扣

    # 3. MACD 正值且扩张 (0-20)
    if dif > 0 and dif > dea:
        score += 20
    elif dif > 0:
        score += 10
    elif macd > 0:
        score += 5

    # 4. 20日涨幅 (0-20)
    if len(kline_rows) >= 20:
        close_20d_ago = float(kline_rows[19]["close"]) if kline_rows[19]["close"] else 0
        if close_20d_ago > 0:
            pct_20d = (close - close_20d_ago) / close_20d_ago
            score += round(min(max(pct_20d / 0.30, 0), 1.0) * 20)

    # 5. 量能配合 (0-15)
    vol_ratio = vol / vol_ma if vol_ma > 0 else 1
    if vol_ratio >= 1.5:
        score += 15
    elif vol_ratio >= 0.8:
        score += round((vol_ratio - 0.8) / 0.7 * 15)

    return min(100, max(0, score))


@app.get("/api/scores/overview")
def get_scores_overview(
    date: str | None = Query(default=None, description="指定日期 YYYY-MM-DD，不传则取各标的最新评分"),

):
    """返回所有标的的评分概览，按分数降序，按信号分组。用于速览买入机会。

    每个标的额外标注 `above_ma5`：收盘价是否站上 MA5（确认反转信号）。
    同时触发 BUY/STRONG_BUY + above_ma5 = 值得关注的买入机会。
    """
    rows = storage.query_scores_overview(date)
    if not rows:
        msg = "暂无评分数据" if not date else f"{date} 暂无评分数据（可能为非交易日）"
        return {"data": None, "message": msg}

    # 为每个标的查最新技术状态（MA5确认 + 动量评分）
    import sqlite3

    from trader_analysis.futu_strategy import config as app_config

    conn = sqlite3.connect(app_config.DB_PATH)
    conn.row_factory = sqlite3.Row
    for r in rows:
        kline_rows = conn.execute(
            "SELECT close, ma5, ma10, ma20, ma60, rsi6, macd, dif, dea, volume, vol_ma20 "
            "FROM kline_indicators WHERE code = ? AND ktype = '1d' ORDER BY date DESC LIMIT 20",
            (r["code"],),
        ).fetchall()
        if kline_rows:
            k = kline_rows[0]
            close = float(k["close"]) if k["close"] else None
            ma5 = float(k["ma5"]) if k["ma5"] else None
            r["close"] = round(close, 2) if close else None
            r["ma5"] = round(ma5, 2) if ma5 else None
            r["above_ma5"] = close > ma5 if (close and ma5) else None

            # 动量评分 (0-100)
            r["momentum_score"] = _calc_momentum(kline_rows)
        else:
            r["above_ma5"] = None
            r["close"] = None
            r["ma5"] = None
            r["momentum_score"] = None
    conn.close()

    # 按信号分组
    strong_buy = [r for r in rows if r["signal"] == "STRONG_BUY"]
    buy = [r for r in rows if r["signal"] == "BUY"]
    no_action = [r for r in rows if r["signal"] == "NO_ACTION"]

    # 统计有多少买入信号同时站上MA5
    actionable = [r for r in rows if r["signal"] in ("STRONG_BUY", "BUY") and r.get("above_ma5")]

    # 动量领先者（主升浪标的）: momentum_score >= 70
    momentum_leaders = sorted(
        [r for r in rows if r.get("momentum_score") and r["momentum_score"] >= 70],
        key=lambda x: x["momentum_score"],
        reverse=True,
    )

    return {
        "date": date or (rows[0]["date"] if rows else None),
        "total_count": len(rows),
        "strong_buy": strong_buy,
        "buy": buy,
        "no_action": no_action,
        "actionable": actionable,
        "momentum_leaders": momentum_leaders,
        "summary": {
            "strong_buy_count": len(strong_buy),
            "buy_count": len(buy),
            "no_action_count": len(no_action),
            "actionable_count": len(actionable),
            "momentum_leaders_count": len(momentum_leaders),
        },
    }


# ── 基本面接口 ────────────────────────────────────────────────────────────────


@app.get("/api/fundamental/latest")
def get_fundamental_latest(
    code: str = Query(...),

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
def get_fundamental_overview():
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
def get_market_temperature():
    """返回最新一期市场温度评分，供前端仪表盘展示。"""
    result = storage.query_latest_market_score()
    if not result:
        return {"data": None, "message": "暂无市场温度数据，请先运行 trader-analysis temperature 命令"}
    return result


@app.get("/api/market-temperature/history")
def get_market_temperature_history(
    days: int = Query(default=30, ge=1, le=365),

):
    """返回近 N 天的市场温度评分历史，用于趋势图。"""
    history = storage.query_market_score_history(days)
    return {"history": history}


# ── 回测接口 ──────────────────────────────────────────────────────────────────


@app.get("/api/backtest/run")
def run_backtest_api(
    code: str = Query(..., description="股票代码 (Futu 格式, 如 US.SNDK)"),
    mode: str = Query(default="hold", description="策略模式: hold(买入持有) / swing(波段操作) / trend(趋势跟踪)"),
    threshold: int = Query(default=40, ge=1, le=100, description="买入评分阈值"),
    holding_days: int = Query(default=10, ge=1, le=250, description="[hold] 持有交易日数"),
    exit_threshold: int = Query(default=30, ge=1, le=100, description="[swing] 卖出评分阈值"),
    max_holding_days: int = Query(default=120, ge=1, le=500, description="[swing/trend] 最大持有天数"),
    trail_ma: str = Query(default="ma5", description="[trend] 跟踪止盈均线: ma5/ma10/ma20"),
    entry_confirm: str = Query(default="none", description="买入确认: none(立即买) / above_ma5(站上MA5再买)"),
    cooldown: str = Query(default="holding", description="去重策略: none/holding/custom"),
    cooldown_days: int | None = Query(default=None, ge=1, le=250, description="custom 模式冷却天数"),
    start_date: str | None = Query(default=None, description="起始日期 YYYY-MM-DD"),
    end_date: str | None = Query(default=None, description="截止日期 YYYY-MM-DD"),
):
    """信号回测：验证评分信号的历史收益表现。支持 hold(买入持有) 和 swing(波段操作) 两种模式。"""
    from trader_analysis.futu_strategy.backtest import BacktestParams, run_backtest

    params = BacktestParams(
        code=code,
        mode=mode,
        threshold=threshold,
        holding_days=holding_days,
        exit_threshold=exit_threshold,
        max_holding_days=max_holding_days,
        trail_ma=trail_ma,
        entry_confirm=entry_confirm,
        cooldown=cooldown,
        cooldown_days=cooldown_days,
        start_date=start_date,
        end_date=end_date,
    )
    return run_backtest(params)


# ── 网格交易接口 ──────────────────────────────────────────────────────────────


@app.get("/api/grid/status")
def get_grid_status(
    config_id: int = Query(..., description="网格配置 ID"),
):
    """查看网格交易运行状态。"""
    from trader_analysis.futu_strategy.grid_trader import state_manager
    from trader_analysis.futu_strategy.grid_trader.strategy import calculate_grid_lines

    state_manager.init_grid_tables()
    cfg = state_manager.get_config(config_id)
    if not cfg:
        return {"data": None, "message": f"Grid config #{config_id} not found"}

    state = state_manager.get_state(config_id)
    grid_lines = calculate_grid_lines(cfg)

    return {
        "config_id": cfg.id,
        "code": cfg.code,
        "status": cfg.status,
        "env": cfg.env,
        "params": {
            "price_upper": cfg.price_upper,
            "price_lower": cfg.price_lower,
            "grid_count": cfg.grid_count,
            "grid_spacing": cfg.grid_spacing,
            "order_qty": cfg.order_qty,
            "max_position": cfg.max_position,
        },
        "state": {
            "current_position": state.current_position,
            "cost_basis": state.cost_basis,
            "daily_pnl": state.daily_pnl,
            "daily_trades": state.daily_trades,
            "last_price": state.last_price,
            "grid_status": state.grid_status,
        },
        "grid_lines": grid_lines,
    }


@app.get("/api/grid/orders")
def get_grid_orders(
    config_id: int = Query(..., description="网格配置 ID"),
    limit: int = Query(default=50, ge=1, le=500),
):
    """查看网格交易记录。"""
    from trader_analysis.futu_strategy.grid_trader import state_manager

    state_manager.init_grid_tables()
    orders = state_manager.query_orders(config_id, limit)
    return {"total": len(orders), "orders": orders}
