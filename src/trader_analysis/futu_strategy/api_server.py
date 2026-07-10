"""API 服务层。

将存储层数据暴露为 HTTP 接口，供前端图表组件消费。
只做读取，不调用 Futu SDK，不做任何计算，可独立于后端运行。
全开放，无需鉴权。

启动：uvicorn trader_analysis.futu_strategy.api_server:app --host 0.0.0.0 --port 8000
文档：http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from trader_analysis.futu_strategy import config, storage, watchlist_storage
from trader_analysis.futu_strategy.market_scorer import compute_asset_temperature
from trader_analysis.futu_strategy.stock_info_fetcher import fetch_stock_info

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
    watchlist_storage.init_watchlist_table()


# ── 公开端点 ──────────────────────────────────────────────────────────────────


@app.get("/health")
def health_check():
    """健康检查。"""
    return {"status": "ok"}


# ── 指标接口 ──────────────────────────────────────────────────────────────────


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


# ── 标的池接口 ────────────────────────────────────────────────────────────────


@app.get("/api/watchlist")
def get_watchlist(
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    market: str | None = Query(default=None),
    search: str | None = Query(default=None),
):
    """返回标的池（支持筛选）。"""
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
    """新增标的。"""
    existing = watchlist_storage.get_stock(body.code)
    if existing:
        return {"data": None, "message": f"Stock {body.code} already exists in watchlist"}
    futu_info = fetch_stock_info(body.code)
    data = body.model_dump()
    if futu_info:
        data.update({k: v for k, v in futu_info.items() if v is not None})
    record = watchlist_storage.add_stock(data)
    return {"message": f"Stock {body.code} added to watchlist", "data": record}


@app.patch("/api/watchlist/{code}")
def update_watchlist_item(code: str, body: dict):
    """修改标的。"""
    existing = watchlist_storage.get_stock(code)
    if not existing:
        return {"data": None, "message": f"Stock {code} not found in watchlist"}
    result, updated_or_violations = watchlist_storage.update_stock(code, body)
    if result is None:
        return {"data": None, "message": f"Fields not editable: {', '.join(updated_or_violations)}"}
    return {"message": f"Stock {code} updated", "data": result, "updated_fields": updated_or_violations}


@app.delete("/api/watchlist/{code}")
def delete_watchlist_item(code: str):
    """删除标的。"""
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
    """刷新标的静态快照字段。"""
    from trader_analysis.futu_strategy.stock_info_fetcher import fetch_snapshot_batch

    codes = [code] if code else watchlist_storage.get_all_codes()
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


# ── 评分概览 ──────────────────────────────────────────────────────────────────


def _calc_momentum(kline_rows: list) -> int:
    """计算动量/趋势强度评分 (0-100)。"""
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

    if all([ma5, ma10, ma20, ma60]):
        if ma5 > ma10 > ma20 > ma60:
            score += 25
        elif ma5 > ma10 > ma20:
            score += 15
        elif ma5 > ma10:
            score += 8

    if 50 <= rsi <= 80:
        score += round((rsi - 50) / 30 * 20)
    elif 80 < rsi <= 90:
        score += 20
    elif rsi > 90:
        score += 15

    if dif > 0 and dif > dea:
        score += 20
    elif dif > 0:
        score += 10
    elif macd > 0:
        score += 5

    if len(kline_rows) >= 20:
        close_20d_ago = float(kline_rows[19]["close"]) if kline_rows[19]["close"] else 0
        if close_20d_ago > 0:
            pct_20d = (close - close_20d_ago) / close_20d_ago
            score += round(min(max(pct_20d / 0.30, 0), 1.0) * 20)

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
    """返回所有标的的评分概览，按分数降序，按信号分组。"""
    rows = storage.query_scores_overview(date)
    if not rows:
        msg = "暂无评分数据" if not date else f"{date} 暂无评分数据（可能为非交易日）"
        return {"data": None, "message": msg}

    import sqlite3
    from trader_analysis.futu_strategy import config as app_config

    conn = sqlite3.connect(app_config.DB_PATH)
    conn.row_factory = sqlite3.Row
    for r in rows:
        kline_rows = conn.execute(
            "SELECT close, ma5, ma10, ma20, ma60, rsi6, macd, dif, dea, volume, vol_ma20,"
            " ema5, ema10, ema15, ema20, ema25, ema30 "
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
            r["momentum_score"] = _calc_momentum(kline_rows)
            # EMA 飘带状态
            e5_raw = k["ema5"]; e30_raw = k["ema30"]
            if e5_raw and e30_raw:
                r["ema_ribbon"] = "green" if float(e5_raw) > float(e30_raw) else "red"
            else:
                r["ema_ribbon"] = None
            # 飘带翻转检测（近5日内）
            ribbon_flip = None
            if r["ema_ribbon"] is not None and len(kline_rows) >= 2:
                current_bull = r["ema_ribbon"] == "green"
                for row in kline_rows[1:6]:
                    e5 = row["ema5"]; e30 = row["ema30"]
                    if e5 and e30:
                        if (float(e5) > float(e30)) != current_bull:
                            ribbon_flip = "to_bull" if current_bull else "to_bear"
                            break
            r["ribbon_flip"] = ribbon_flip
        else:
            r["above_ma5"] = None
            r["close"] = None
            r["ma5"] = None
            r["momentum_score"] = None
            r["ema_ribbon"] = None
            r["ribbon_flip"] = None
    conn.close()

    strong_buy = [r for r in rows if r["signal"] == "STRONG_BUY"]
    buy = [r for r in rows if r["signal"] == "BUY"]
    no_action = [r for r in rows if r["signal"] == "NO_ACTION"]
    actionable = [r for r in rows if r["signal"] in ("STRONG_BUY", "BUY") and r.get("above_ma5")]
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


# ── 市场温度接口 ──────────────────────────────────────────────────────────────


@app.get("/api/market-temperature")
def get_market_temperature():
    """返回最新一期市场温度评分，附加黄金/BTC 单资产温度（实时计算）。"""
    result = storage.query_latest_market_score()
    if not result:
        return {"data": None, "message": "暂无市场温度数据，请先运行 trader-analysis temperature 命令"}
    result["gld_temp"] = compute_asset_temperature("GLD")
    result["btc_temp"] = compute_asset_temperature("BTC")
    return result


@app.get("/api/market-temperature/history")
def get_market_temperature_history(
    days: int = Query(default=30, ge=1, le=365),
):
    """返回近 N 天的市场温度评分历史。"""
    history = storage.query_market_score_history(days)
    return {"history": history}


@app.get("/api/asset-temperature/history")
def get_asset_temperature_history(
    asset: str = Query(..., description="资产 key：GLD 或 BTC"),
    days: int = Query(default=60, ge=1, le=365),
):
    """返回单资产（黄金/比特币）历史温度评分序列（实时计算，较慢）。"""
    from trader_analysis.futu_strategy.market_scorer import compute_asset_temperature_history
    history = compute_asset_temperature_history(asset, days)
    return {"asset": asset, "history": history}


# ── 回测接口 ──────────────────────────────────────────────────────────────────


@app.get("/api/backtest/run")
def run_backtest_api(
    code: str = Query(..., description="股票代码 (Futu 格式, 如 US.SNDK)"),
    mode: str = Query(default="hold", description="策略模式: hold / swing / trend"),
    threshold: int = Query(default=40, ge=1, le=100),
    holding_days: int = Query(default=10, ge=1, le=250),
    exit_threshold: int = Query(default=30, ge=1, le=100),
    max_holding_days: int = Query(default=120, ge=1, le=500),
    trail_ma: str = Query(default="ma5"),
    entry_confirm: str = Query(default="none"),
    cooldown: str = Query(default="holding"),
    cooldown_days: int | None = Query(default=None, ge=1, le=250),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
):
    """信号回测。"""
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


# ── TP/SL 接口 ────────────────────────────────────────────────────────────────


@app.get("/api/tp-sl")
def get_tp_sl(
    code: str = Query(...),
    atr_multiplier: float = Query(default=2.0, ge=0.5, le=5.0),
    min_rr_ratio: float = Query(default=2.0, ge=1.0, le=10.0),
):
    """计算自动止盈/止损价位和风险回报比。"""
    from trader_analysis.futu_strategy import config as app_config
    from trader_analysis.futu_strategy.tp_sl import calculate_tp_sl

    daily_df = storage.query_recent(code, "1d", limit=250)
    if daily_df.empty:
        return {"data": None, "message": f"{code} 暂无日线数据，请等待历史数据导入完成"}

    return calculate_tp_sl(
        code=code,
        daily_df=daily_df,
        atr_period=app_config.TPSL_ATR_PERIOD,
        atr_multiplier=atr_multiplier,
        swing_lookback=app_config.TPSL_SWING_LOOKBACK,
        swing_distance=app_config.TPSL_SWING_DISTANCE,
        min_rr_ratio=min_rr_ratio,
    )


# ── 网格交易接口 ──────────────────────────────────────────────────────────────


@app.get("/api/grid/status")
def get_grid_status(
    config_id: int = Query(...),
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
    config_id: int = Query(...),
    limit: int = Query(default=50, ge=1, le=500),
):
    """查看网格交易记录。"""
    from trader_analysis.futu_strategy.grid_trader import state_manager

    state_manager.init_grid_tables()
    orders = state_manager.query_orders(config_id, limit)
    return {"total": len(orders), "orders": orders}


# ── 顶背离信号接口 ────────────────────────────────────────────────────────────


@app.get("/api/trade-signals")
def get_trade_signals(code: str = Query(..., description="标的代码")):
    """实时运行顶/底背离检测，返回完整信号清单（含触发状态和操作建议）。

    每个信号包含：signal_type / category / triggered / strength / description / label / action / action_type
    前端据此渲染左右分栏"交易信号"板块。
    """
    from trader_analysis.futu_strategy.bottom_detector import detect_all_bottom
    from trader_analysis.futu_strategy.top_detector import detect_all

    daily_df = storage.query_recent(code, "1d", limit=300)
    if daily_df.empty or len(daily_df) < 30:
        return {"data": None, "message": f"{code} 数据不足，请先更新行情"}

    date = str(daily_df.iloc[-1]["date"]) if "date" in daily_df.columns else ""

    # ── 顶部信号检测 ──────────────────────────────────────────────────────────
    _TOP_META = {
        "NEAR_HIGH":        {"label": "接近前高",     "action": "注意减仓",     "action_type": "sell_warn"},
        "RSI_TOP_DIV":      {"label": "RSI顶背离",    "action": "建议减仓1/3",  "action_type": "sell_1"},
        "MACD_TOP_DIV":     {"label": "MACD顶背离",   "action": "建议减仓1/3",  "action_type": "sell_1"},
        "VOLUME_STALL":     {"label": "天量滞涨",     "action": "注意减仓",     "action_type": "sell_warn"},
        "UPPER_SHADOW":     {"label": "连续长上影线",  "action": "注意减仓",     "action_type": "sell_warn"},
        "BOLL_SQUEEZE":     {"label": "布林高位收口",  "action": "注意减仓",     "action_type": "sell_warn"},
        "ACCELERATION":     {"label": "加速赶顶",     "action": "注意减仓",     "action_type": "sell_warn"},
        "BREAK_MA5":        {"label": "跌破MA5",      "action": "减仓2/3",      "action_type": "sell_2"},
        "MA5_DEATH_CROSS":  {"label": "MA5死叉MA10",  "action": "建议清仓",     "action_type": "sell_3"},
        "MA5_NO_RECOVERY":  {"label": "连续未站回MA5", "action": "建议清仓",     "action_type": "sell_3"},
        "EMERGENCY_STOP":   {"label": "紧急止损",     "action": "立即清仓",     "action_type": "sell_emergency"},
    }

    _BOTTOM_META = {
        "NEAR_LOW":          {"label": "接近近期低点",  "action": "关注买入机会", "action_type": "buy_watch"},
        "RSI_BOTTOM_DIV":    {"label": "RSI底背离",    "action": "关注买入机会", "action_type": "buy_watch"},
        "MACD_BOTTOM_DIV":   {"label": "MACD底背离",   "action": "关注买入机会", "action_type": "buy_watch"},
        "PANIC_VOLUME":      {"label": "恐慌放量缩量",  "action": "关注买入机会", "action_type": "buy_watch"},
    }

    triggered_top = {s.signal_type: s for s in detect_all(daily_df)}
    triggered_bottom = {s.signal_type: s for s in detect_all_bottom(daily_df)}

    top_signals = []
    for sig_type, meta in _TOP_META.items():
        if sig_type in triggered_top:
            s = triggered_top[sig_type]
            top_signals.append({
                "signal_type": sig_type,
                "category": "top",
                "triggered": True,
                "strength": s.strength,
                "description": s.description,
                **meta,
            })
        else:
            top_signals.append({
                "signal_type": sig_type,
                "category": "top",
                "triggered": False,
                "strength": 0.0,
                "description": "未检测到",
                **meta,
            })

    bottom_signals = []
    for sig_type, meta in _BOTTOM_META.items():
        if sig_type in triggered_bottom:
            s = triggered_bottom[sig_type]
            bottom_signals.append({
                "signal_type": sig_type,
                "category": "bottom",
                "triggered": True,
                "strength": s.strength,
                "description": s.description,
                **meta,
            })
        else:
            bottom_signals.append({
                "signal_type": sig_type,
                "category": "bottom",
                "triggered": False,
                "strength": 0.0,
                "description": "未检测到",
                **meta,
            })

    return {
        "code": code,
        "date": date,
        "top_signals": top_signals,
        "bottom_signals": bottom_signals,
        "top_triggered_count": sum(1 for s in top_signals if s["triggered"]),
        "bottom_triggered_count": sum(1 for s in bottom_signals if s["triggered"]),
    }


@app.get("/api/top-signals")
def get_top_signals(
    code: str | None = Query(default=None, description="标的代码，不传则返回所有标的近期信号"),
    days: int = Query(default=7, ge=1, le=90),
):
    """返回顶部信号历史。可按单只标的或全部标的查询。"""
    if code:
        data = storage.query_top_signals(code, days)
        return {"code": code, "days": days, "count": len(data), "signals": data}
    else:
        data = storage.query_top_signals_all(days)
        return {"days": days, "count": len(data), "signals": data}


@app.get("/api/position-states")
def get_position_states(
    code: str | None = Query(default=None, description="标的代码，不传则返回所有非 EMPTY 持仓"),
):
    """返回持仓状态。"""
    if code:
        state = storage.get_position_state(code)
        return state
    else:
        states = storage.list_active_positions()
        return {"total": len(states), "positions": states}


@app.get("/api/sell-log")
def get_sell_log(
    code: str | None = Query(default=None, description="标的代码，不传则返回全部"),
    days: int = Query(default=30, ge=1, le=365),
):
    """返回卖出日志（从 trade_log.jsonl 读取 SELL 类型记录）。"""
    import json as _json
    import os
    from trader_analysis.futu_strategy import config as _cfg

    log_file = _cfg.TRADE_LOG_FILE
    if not os.path.exists(log_file):
        return {"total": 0, "records": []}

    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    records = []
    try:
        with open(log_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = _json.loads(line)
                except Exception:
                    continue
                # 只返回 SELL 类记录
                if not rec.get("signal", "").startswith("SELL_"):
                    continue
                ts = rec.get("timestamp", "")
                if ts[:10] < cutoff:
                    continue
                if code and rec.get("code") != code:
                    continue
                records.append(rec)
    except Exception:
        pass

    records.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return {"total": len(records), "records": records}


# ── 技术分析辅助决策 ──────────────────────────────────────────────────────────


@app.get("/api/analysis")
def get_analysis(
    code: str,
    ktype: str = Query(default="1d", pattern="^(1d|1w)$"),
):
    """返回支撑/压力位、技术形态信号、趋势判断，辅助个股决策。

    基于本地 DB 中的 OHLCV + 技术指标计算，无需 OpenD。
    """
    from trader_analysis.futu_strategy.technical_analysis import (
        analyze_trend,
        detect_patterns,
        find_support_resistance,
    )

    df = storage.query_recent(code, ktype, limit=120)
    if df.empty or len(df) < 20:
        return {"data": None, "message": f"{code} 数据不足（需至少 20 根），请先更新行情"}

    supports, resistances = find_support_resistance(df)
    patterns = detect_patterns(df)
    trend = analyze_trend(df)

    last = df.iloc[-1]
    return {
        "code": code,
        "ktype": ktype,
        "date": last["date"],
        "close": float(last["close"]),
        "supports": supports,
        "resistances": resistances,
        "patterns": patterns,
        "trend": trend,
    }
