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
    ktype: str = Query(default="1d", pattern="^(1d|4h|1w)$"),
    days: int = Query(default=60, ge=1, le=500),
):
    """返回某标的某周期最近 N 根 K 线 + 全部指标（日期升序，供图表使用）。"""
    rows = storage.query_range(code, ktype, days)
    if not rows:
        ktype_label = {"1d": "日线", "4h": "4小时线", "1w": "周线"}.get(ktype, ktype)
        return {
            "code": code,
            "ktype": ktype,
            "data": [],
            "message": f"{code} 暂无{ktype_label}数据，请等待历史数据导入完成",
        }
    # 4H 数据将日期转为 Unix 时间戳（秒），供轻量级图表正确显示
    if ktype == "4h":
        from datetime import datetime as dt
        for r in rows:
            if r.get("date"):
                try:
                    r["date"] = int(dt.strptime(r["date"], "%Y-%m-%d %H:%M:%S").timestamp())
                except (ValueError, TypeError):
                    pass
    return {"code": code, "ktype": ktype, "data": rows}


@app.get("/api/indicators/latest")
def get_latest(
    code: str,
    ktype: str = Query(default="1d", pattern="^(1d|4h|1w)$"),
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

    # 批量查询最新日线收盘价、标签
    conn = storage._get_conn()
    placeholders = ",".join("?" * len(items))
    kline_rows = conn.execute(
        f"""SELECT code, close FROM (
            SELECT code, close, ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) as rn
            FROM kline_indicators WHERE ktype='1d' AND code IN ({placeholders})
        ) WHERE rn=1""",
        [item["code"] for item in items],
    ).fetchall()
    close_map = {r["code"]: float(r["close"]) for r in kline_rows if r["close"]}
    conn.close()

    for item in items:
        code = item["code"]
        item["has_data"] = code in codes_in_db
        # 加最新收盘价和晨星折价
        latest_close = close_map.get(code)
        item["latest_close"] = round(latest_close, 2) if latest_close else None
        ms_value = item.get("morningstar_fair_value")
        category_tag = item.get("category", "")
        is_etf = "etf" in category_tag.lower() or "sector_etf" in category_tag.lower()
        if latest_close and ms_value and not is_etf:
            discount = round((float(ms_value) - latest_close) / latest_close * 100, 1)
            item["ms_discount_pct"] = discount
        else:
            item["ms_discount_pct"] = None

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

    # 批量查询：一次拉取所有标的最近20根日线
    # 先找出截止日期（只取最近 30 天数据减少扫描量）
    codes = [r["code"] for r in rows]
    placeholders = ",".join(["?"] * len(codes))
    from datetime import datetime, timedelta
    cutoff_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    all_kline_rows = conn.execute(
        f"""SELECT code, close, ma5, ma10, ma20, ma60, rsi6, macd, dif, dea, volume, vol_ma20,
            ema5, ema10, ema15, ema20, ema25, ema30, date
        FROM kline_indicators
        WHERE code IN ({placeholders}) AND ktype = '1d' AND date >= ?
        ORDER BY code, date DESC""",
        codes + [cutoff_date],
    ).fetchall()

    # 按 code 分组（只保留最近 20 根）
    kline_by_code: dict[str, list] = {}
    for row in all_kline_rows:
        code = row["code"]
        if code not in kline_by_code:
            kline_by_code[code] = []
        if len(kline_by_code[code]) < 20:
            kline_by_code[code].append(row)

    for r in rows:
        kline_rows = kline_by_code.get(r["code"], [])
        if kline_rows:
            k = kline_rows[0]  # 最新一根（rn=1）
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


# ── EMA 交叉信号接口 ──────────────────────────────────────────────────────────


@app.get("/api/ema-cross-signals")
def get_ema_cross_signals(
    date: str | None = Query(default=None, description="指定日期(YYYY-MM-DD)，查该日期的信号"),
):
    """查询 EMA 交叉信号（日线+4H两个维度）。

    - 不传 date：实时计算最新信号（遍历全部标的，基于最新 K 线）
    - 传 date：从 DB 读取该日期已存储的信号（需先 scan-signals --backfill）
    """
    import json as _json

    if not date:
        # ── 实时计算模式：遍历全部标的，基于最新 K 线检测 EMA5/30 交叉 ──
        from trader_analysis.futu_strategy import config as _cfg
        from trader_analysis.futu_strategy.ema_cross_detector import detect_ema_cross

        conn = storage._get_conn()
        name_map = {
            r["code"]: (r["name"] or "")
            for r in conn.execute("SELECT code, name FROM watchlist").fetchall()
        }
        conn.close()

        bull_1d, bull_4h, bear_1d, bear_4h = [], [], [], []

        def _to_item(code, sig):
            return {
                "code": code,
                "date": sig.detail.get("date", ""),
                "signal_type": sig.signal_type,
                "strength": round(sig.strength, 3),
                "detail": sig.detail,
                "name": name_map.get(code, ""),
            }

        for code in list(_cfg.WATCHLIST):
            daily_df = storage.query_recent(code, "1d", limit=60)
            if len(daily_df) >= 2:
                for sig in detect_ema_cross(daily_df, timeframe="1d"):
                    item = _to_item(code, sig)
                    if sig.signal_type == "EMA_CROSS_BULL_1D":
                        bull_1d.append(item)
                    else:
                        bear_1d.append(item)

            four_h_df = storage.query_recent(code, "4h", limit=120)
            if len(four_h_df) >= 2:
                for sig in detect_ema_cross(four_h_df, timeframe="4h"):
                    item = _to_item(code, sig)
                    if sig.signal_type == "EMA_CROSS_BULL_4H":
                        bull_4h.append(item)
                    else:
                        bear_4h.append(item)

        for lst in (bull_1d, bull_4h, bear_1d, bear_4h):
            lst.sort(key=lambda x: -x["strength"])

        return {
            "bull_1d": bull_1d,
            "bull_4h": bull_4h,
            "bear_1d": bear_1d,
            "bear_4h": bear_4h,
            "total": len(bull_1d) + len(bull_4h) + len(bear_1d) + len(bear_4h),
        }

    conn = storage._get_conn()

    if date:
        # 精确匹配该日期写入的信号
        date_filter = "AND date = ?"
        params = (date,)
    else:
        # 取最近一次 scan 的日期
        row = conn.execute(
            "SELECT MAX(date) as d FROM bottom_signal_log WHERE signal_type LIKE 'EMA_CROSS%'"
        ).fetchone()
        latest = row["d"] if row else None
        if not latest:
            conn.close()
            return {"bull_1d": [], "bull_4h": [], "bear_1d": [], "bear_4h": [], "total": 0}
        date_filter = "AND date = ?"
        params = (latest,)

    # 从底部信号表取 BULL（空转多）
    bull_rows = conn.execute(
        "SELECT code, date, signal_type, strength, detail_json, created_at "
        "FROM bottom_signal_log WHERE signal_type LIKE 'EMA_CROSS_BULL%' "
        f"{date_filter} ORDER BY strength DESC",
        params,
    ).fetchall()

    # 从顶部信号表取 BEAR（多转空）
    bear_rows = conn.execute(
        "SELECT code, date, signal_type, strength, detail_json, created_at "
        "FROM top_signal_log WHERE signal_type LIKE 'EMA_CROSS_BEAR%' "
        f"{date_filter} ORDER BY strength DESC",
        params,
    ).fetchall()
    conn.close()

    def _parse(rows):
        result = []
        for r in rows:
            d = dict(r)
            d["detail"] = _json.loads(d.pop("detail_json", "{}") or "{}")
            # 补充 name
            d["name"] = d["detail"].get("name", "")
            result.append(d)
        return result

    bull_signals = _parse(bull_rows)
    bear_signals = _parse(bear_rows)

    # 按维度分组
    return {
        "bull_1d": [s for s in bull_signals if s["signal_type"] == "EMA_CROSS_BULL_1D"],
        "bull_4h": [s for s in bull_signals if s["signal_type"] == "EMA_CROSS_BULL_4H"],
        "bear_1d": [s for s in bear_signals if s["signal_type"] == "EMA_CROSS_BEAR_1D"],
        "bear_4h": [s for s in bear_signals if s["signal_type"] == "EMA_CROSS_BEAR_4H"],
        "total": len(bull_signals) + len(bear_signals),
    }


# ── 顶背离信号接口 ────────────────────────────────────────────────────────────


@app.get("/api/trade-signals")
def get_trade_signals(
    code: str = Query(..., description="标的代码"),
    date: str | None = Query(default=None, description="日期(YYYY-MM-DD)，不传则实时计算最新"),
):
    """交易信号检测。

    - 不传 date：实时运行顶/底信号检测（基于最新数据）
    - 传 date：从 DB 读取该日期已存储的信号（需先 scan-signals --backfill）

    每个信号包含：signal_type / category / triggered / strength / description / label / action / action_type
    """
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
        "MA5_NO_RECOVERY":  {"label": "持续调整",       "action": "观望",         "action_type": "sell_warn"},
        "EMERGENCY_STOP":   {"label": "紧急止损",     "action": "立即清仓",     "action_type": "sell_emergency"},
    }

    _BOTTOM_META = {
        "NEAR_SUPPORT":     {"label": "均线支撑",   "action": "关注",       "action_type": "buy_watch"},
        "DEEP_V":           {"label": "深V确认",    "action": "试探建仓",   "action_type": "buy_1"},
        "VOLUME_SHRINK":    {"label": "缩量企稳",   "action": "关注",       "action_type": "buy_watch"},
        "RSI_BOTTOM_DIV":   {"label": "RSI底背离",  "action": "加仓确认",   "action_type": "buy_2"},
        "W_BOTTOM":         {"label": "W底形态",    "action": "加仓确认",   "action_type": "buy_2"},
        "SUPPORT_CONFIRM":  {"label": "支撑确认",   "action": "关注",       "action_type": "buy_watch"},
        "RECLAIM_MA5":      {"label": "站上MA5",    "action": "建仓完成",   "action_type": "buy_3"},
    }

    if date:
        # ── 从 DB 读取已存储的信号 ─────────────────────────────────────────────
        import sqlite3, json as _json
        from trader_analysis.futu_strategy import config as _cfg
        conn = sqlite3.connect(_cfg.DB_PATH)
        conn.row_factory = sqlite3.Row

        top_rows = conn.execute(
            "SELECT signal_type, strength, detail_json FROM top_signal_log "
            "WHERE code = ? AND date = ?", (code, date)
        ).fetchall()
        bottom_rows = conn.execute(
            "SELECT signal_type, strength, detail_json FROM bottom_signal_log "
            "WHERE code = ? AND date = ?", (code, date)
        ).fetchall()
        conn.close()

        triggered_top = {r["signal_type"]: r for r in top_rows}
        triggered_bottom = {r["signal_type"]: r for r in bottom_rows}

        def _build_desc(sig_type: str, detail: dict, meta: dict) -> str:
            """从 detail 数据生成可读描述。"""
            label = meta["label"]
            if "close" in detail and "ma5" in detail:
                return f"{label}: close={detail['close']}, ma5={detail['ma5']}"
            if "distance_pct" in detail:
                return f"{label}: 距离{detail['distance_pct']*100:.1f}%"
            if "rsi1" in detail and "rsi2" in detail:
                return f"{label}: RSI从{detail['rsi1']}至{detail['rsi2']}"
            if "macd1" in detail and "macd2" in detail:
                return f"{label}: MACD从{detail['macd1']}至{detail['macd2']}"
            if "vol_ratio" in detail:
                return f"{label}: 量比={detail['vol_ratio']}x"
            if "shadow_ratio" in detail:
                return f"{label}: 下影线占比{detail['shadow_ratio']*100:.0f}%"
            if "ratio" in detail:
                return f"{label}: 比率={detail['ratio']}"
            if "gain_pct" in detail:
                return f"{label}: 涨幅{detail['gain_pct']*100:.1f}%"
            return f"{label}触发 (强度{detail.get('strength', '')})"

        top_signals = []
        for sig_type, meta in _TOP_META.items():
            if sig_type in triggered_top:
                r = triggered_top[sig_type]
                detail = _json.loads(r["detail_json"]) if r["detail_json"] else {}
                top_signals.append({
                    "signal_type": sig_type, "category": "top", "triggered": True,
                    "strength": r["strength"],
                    "description": _build_desc(sig_type, detail, meta), **meta,
                })
            else:
                top_signals.append({
                    "signal_type": sig_type, "category": "top", "triggered": False,
                    "strength": 0.0, "description": "未检测到", **meta,
                })

        bottom_signals = []
        for sig_type, meta in _BOTTOM_META.items():
            if sig_type in triggered_bottom:
                r = triggered_bottom[sig_type]
                detail = _json.loads(r["detail_json"]) if r["detail_json"] else {}
                bottom_signals.append({
                    "signal_type": sig_type, "category": "bottom", "triggered": True,
                    "strength": r["strength"],
                    "description": _build_desc(sig_type, detail, meta), **meta,
                })
            else:
                bottom_signals.append({
                    "signal_type": sig_type, "category": "bottom", "triggered": False,
                    "strength": 0.0, "description": "未检测到", **meta,
                })

        return {
            "code": code, "date": date,
            "top_signals": top_signals, "bottom_signals": bottom_signals,
            "top_triggered_count": sum(1 for s in top_signals if s["triggered"]),
            "bottom_triggered_count": sum(1 for s in bottom_signals if s["triggered"]),
        }

    # ── 实时计算（无 date 参数）────────────────────────────────────────────────
    from trader_analysis.futu_strategy.bottom_detector import detect_all as detect_all_bottom
    from trader_analysis.futu_strategy.top_detector import detect_all

    daily_df = storage.query_recent(code, "1d", limit=300)
    if daily_df.empty or len(daily_df) < 30:
        return {"data": None, "message": f"{code} 数据不足，请先更新行情"}

    resp_date = str(daily_df.iloc[-1]["date"]) if "date" in daily_df.columns else ""

    triggered_top = {s.signal_type: s for s in detect_all(daily_df)}
    triggered_bottom = {s.signal_type: s for s in detect_all_bottom(daily_df)}

    top_signals = []
    for sig_type, meta in _TOP_META.items():
        if sig_type in triggered_top:
            s = triggered_top[sig_type]
            top_signals.append({
                "signal_type": sig_type, "category": "top", "triggered": True,
                "strength": s.strength, "description": s.description, **meta,
            })
        else:
            top_signals.append({
                "signal_type": sig_type, "category": "top", "triggered": False,
                "strength": 0.0, "description": "未检测到", **meta,
            })

    bottom_signals = []
    for sig_type, meta in _BOTTOM_META.items():
        if sig_type in triggered_bottom:
            s = triggered_bottom[sig_type]
            bottom_signals.append({
                "signal_type": sig_type, "category": "bottom", "triggered": True,
                "strength": s.strength, "description": s.description, **meta,
            })
        else:
            bottom_signals.append({
                "signal_type": sig_type, "category": "bottom", "triggered": False,
                "strength": 0.0, "description": "未检测到", **meta,
            })

    return {
        "code": code, "date": resp_date,
        "top_signals": top_signals, "bottom_signals": bottom_signals,
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


@app.get("/api/bottom-signals")
def get_bottom_signals(
    code: str | None = Query(default=None, description="标的代码，不传则返回所有标的近期信号"),
    days: int = Query(default=7, ge=1, le=90),
):
    """返回底部信号历史。可按单只标的或全部标的查询。"""
    if code:
        data = storage.query_bottom_signals(code, days)
        return {"code": code, "days": days, "count": len(data), "signals": data}
    else:
        data = storage.query_bottom_signals_all(days)
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


def _score_pattern_confidence(
    patterns: list[dict],
    dow: dict,
    valuation: str,
) -> list[dict]:
    """根据道氏趋势和估值给每个形态信号标注置信度。"""
    tide = dow.get("tide", "neutral")
    wave = dow.get("wave", "neutral")

    def _conf(is_bullish: bool | None) -> dict:
        """判断信号与趋势的共振程度"""
        if is_bullish is None:
            return {"level": "medium", "label": "中性", "note": ""}
        if is_bullish and tide == "up":
            note = "与涨潮共振，置信度高"
            if valuation == "undervalued":
                note = "涨潮+低估共振，置信度很高"
            return {"level": "high", "label": "高", "note": note}
        elif not is_bullish and tide == "down":
            return {"level": "high", "label": "高", "note": "与退潮共振，置信度高"}
        elif is_bullish and tide == "down":
            return {"level": "low", "label": "低", "note": "逆退潮做多，置信度低"}
        elif not is_bullish and tide == "up":
            return {"level": "low", "label": "低", "note": "逆涨潮看空，置信度低"}
        return {"level": "medium", "label": "中", "note": "潮汐不明，置信度一般"}

    for p in patterns:
        pid = p["id"]
        conf = _conf(p.get("bullish"))

        # 特殊情况增强
        if "rsioos" in pid and tide == "up":
            if wave == "down":
                conf["note"] = "涨潮回调中的超卖，加仓良机"
                conf["level"] = "high"
            if valuation == "undervalued":
                conf["note"] = "低估+涨潮超卖，最佳做多信号"
                conf["level"] = "high"
        elif "macd_golden" in pid and tide == "up":
            conf["note"] = "顺势金叉，可信度高"
            conf["level"] = "high"
        elif "ma_bull" in pid and tide == "up" and valuation == "undervalued":
            conf["note"] = "涨潮+低估+多头排列，强做多信号"
        elif "ena_ribbon_bull" in pid and tide == "up":
            conf["note"] = "涨潮中EMA飘带多头，动能确认"

        p["confidence"] = conf

    # 按置信度排序：高 → 中 → 低，同级 bullish 优先
    order = {"high": 0, "medium": 1, "low": 2}
    patterns.sort(key=lambda p: (order.get(p.get("confidence", {}).get("level", "medium"), 1),
                                   p.get("bullish") is not True))
    return patterns


def _enhance_levels(
    supports: list[dict],
    resistances: list[dict],
    close: float,
    dow: dict,
) -> dict:
    """增强支撑/压力位：加道氏上下文、MA60 标记、做多做空盈亏比。"""
    tide_label = {"up": "涨潮", "down": "退潮", "neutral": "无潮汐"}.get(dow.get("tide", ""), "")

    def _add_context(levels: list[dict], is_support: bool) -> list[dict]:
        """给每个 level 加道氏上下文描述"""
        for lv in levels:
            pct = round(abs(lv["price"] - close) / close * 100, 1)
            lv["pct"] = pct

            # MA60 特殊标记
            is_ma60 = lv.get("label", "").startswith("MA60")
            lv["is_key"] = is_ma60

            # 道氏上下文
            if is_ma60 and tide_label:
                if is_support and dow.get("tide") == "up":
                    cntx = f"{tide_label}中MA60支撑有效性高"
                elif not is_support and dow.get("tide") == "down":
                    cntx = f"{tide_label}中MA60压力有效性高"
                else:
                    cntx = f"MA60{'支撑' if is_support else '压力'} · {tide_label}"
            elif dow.get("tide") == "up" and is_support:
                cntx = f"{tide_label}中支撑有效性较高"
            elif dow.get("tide") == "down" and not is_support:
                cntx = f"{tide_label}中压力有效性较高"
            else:
                cntx = ""
            if cntx:
                lv["dow_context"] = cntx
        return levels

    supports = _add_context(supports, is_support=True)
    resistances = _add_context(resistances, is_support=False)

    # ── 盈亏比 ──
    # 做多: 止损=最近支撑(或-5%), 止盈=最近压力(��+10%)
    # 做空: 止损=最近压力(或+5%), 止盈=最近支撑(或-10%)
    nearest_support = max((s["price"] for s in supports), default=None) if supports else None
    nearest_resistance = min((r["price"] for r in resistances), default=None) if resistances else None

    rr = {}
    # 做多
    long_stop = nearest_support if nearest_support else close * 0.95
    long_target = nearest_resistance if nearest_resistance else close * 1.10
    long_risk = close - long_stop
    long_reward = long_target - close
    if long_risk > 0:
        rr["long_rr"] = round(long_reward / long_risk, 1)
        rr["long_stop"] = round(long_stop, 2)
        rr["long_target"] = round(long_target, 2)
    else:
        rr["long_rr"] = rr["long_stop"] = rr["long_target"] = None

    # 做空
    short_stop = nearest_resistance if nearest_resistance else close * 1.05
    short_target = nearest_support if nearest_support else close * 0.90
    short_risk = short_stop - close
    short_reward = close - short_target
    if short_risk > 0:
        rr["short_rr"] = round(short_reward / short_risk, 1)
        rr["short_stop"] = round(short_stop, 2)
        rr["short_target"] = round(short_target, 2)
    else:
        rr["short_rr"] = rr["short_stop"] = rr["short_target"] = None

    return {"supports": supports, "resistances": resistances, "risk_reward": rr}


@app.get("/api/analysis")
def get_analysis(
    code: str,
    ktype: str = Query(default="1d", pattern="^(1d|1w)$"),
    date: str | None = Query(default=None, description="指定日期 YYYY-MM-DD，不传取最新"),
):
    """返回支撑/压力位、技术形态信号、趋势判断，辅助个股决策。

    基于本地 DB 中的 OHLCV + 技术指标计算，无需 OpenD。
    """
    from trader_analysis.futu_strategy.technical_analysis import (
        analyze_dow_trend,
        analyze_trend,
        detect_patterns,
        find_support_resistance,
    )

    df = storage.query_recent(code, ktype, limit=120)
    if df.empty or len(df) < 20:
        return {"data": None, "message": f"{code} 数据不足（需至少 20 根），请先更新行情"}
    if date:
        df = df[df["date"] <= str(date)]
        if df.empty or len(df) < 20:
            return {"data": None, "message": f"{code} 在 {date} 之前数据不足（需至少 20 根）"}

    supports, resistances = find_support_resistance(df)
    trend = analyze_trend(df)

    # 道氏三层趋势（需要周线数据 + 晨星估值）
    weekly_df = storage.query_recent(code, "1w", limit=60)
    morningstar = None
    try:
        tmp_conn = storage._get_conn()
        ms_row = tmp_conn.execute(
            "SELECT morningstar_fair_value FROM watchlist WHERE code=?", (code,)
        ).fetchone()
        if ms_row and ms_row["morningstar_fair_value"]:
            morningstar = float(ms_row["morningstar_fair_value"])
        tmp_conn.close()
    except Exception:
        pass
    close_price = float(df.iloc[-1]["close"]) if not df.empty else None
    dow_theory = analyze_dow_trend(df, weekly_df, morningstar, close_price)

    # 形态检测（在道氏之后再算，可以加置信度）
    patterns = detect_patterns(df)
    patterns = _score_pattern_confidence(patterns, dow_theory, dow_theory.get("valuation", "fair"))

    # ── 增强关键位置：加道氏上下文 + 盈亏比 ──
    enhanced_levels = _enhance_levels(supports, resistances, close_price, dow_theory)
    supports = enhanced_levels["supports"]
    resistances = enhanced_levels["resistances"]

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
        "dow_theory": dow_theory,
        "risk_reward": enhanced_levels["risk_reward"],
    }


# ── 基本面估值 ──────────────────────────────────────────────────────────────


@app.get("/api/daily-picks")
def get_daily_picks(
    date: str | None = Query(default=None, description="指定日期 YYYY-MM-DD"),
):
    """返回今日最佳做多标的：基本面低估 + 周线涨潮 + 日线回调 + 评分≥90。

    巴菲特原则：不懂不做，不做空，不借钱。
    筛选逻辑：好公司（低估）+ 好位置（周线上涨+日线回调）+ 好价格（评分≥{config.DAILY_PICKS_MIN_SCORE}）。
    """
    conn = storage._get_conn()
    picks = []
    min_score = config.DAILY_PICKS_MIN_SCORE

    # 1. 找出评分 ≥ 阈值的标的（超卖+技术面严重偏离均值）
    if date:
        score_rows = conn.execute(
            f"SELECT code, total_score FROM score_results WHERE date = ? AND total_score >= {min_score} ORDER BY total_score DESC",
            (date,),
        ).fetchall()
    else:
        # 取最近一个有 ≥10 个评分的日期
        latest_full = conn.execute(
            "SELECT date, COUNT(*) as n FROM score_results GROUP BY date HAVING n >= 10 ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if not latest_full:
            conn.close()
            return {"data": [], "message": "暂无足够评分数据"}
        date = str(latest_full["date"])
        score_rows = conn.execute(
            f"SELECT code, total_score FROM score_results WHERE date = ? AND total_score >= {min_score} ORDER BY total_score DESC",
            (date,),
        ).fetchall()

    if not score_rows:
        conn.close()
        return {"data": [], "message": f"{date} 无评分≥{min_score}的标的"}

    # 批量查晨星公允价值
    codes = [r["code"] for r in score_rows]
    ph = ",".join("?" * len(codes))
    ms_rows = conn.execute(
        f"SELECT code, morningstar_fair_value FROM watchlist WHERE code IN ({ph})",
        codes,
    ).fetchall()
    ms_map = {r["code"]: float(r["morningstar_fair_value"]) for r in ms_rows if r["morningstar_fair_value"]}
    conn.close()

    # 2. 逐个跑道氏分析
    from trader_analysis.futu_strategy.technical_analysis import analyze_dow_trend

    for sr in score_rows:
        code = sr["code"]
        score = sr["total_score"]
        ms_value = ms_map.get(code)
        if not ms_value:
            continue

        daily_df = storage.query_recent(code, "1d", limit=120)
        weekly_df = storage.query_recent(code, "1w", limit=60)
        if daily_df.empty or len(daily_df) < 20:
            continue

        close = float(daily_df.iloc[-1]["close"])
        if close <= 0:
            continue

        # 筛选：必须低估（收盘价 < 晨星价值）
        discount = round((ms_value - close) / close * 100, 1)
        if discount <= 0:
            continue

        dow = analyze_dow_trend(daily_df, weekly_df, ms_value, close)

        # 筛选：周线涨潮 + 日线回调或超卖
        if dow["tide"] != "up":
            continue
        ripple_rsi = dow["ripple"].get("rsi12")
        wave = dow["wave"]
        if wave not in ("down", "neutral") and (ripple_rsi is None or ripple_rsi >= 40):
            continue  # 波浪不回调且涟漪也不超卖，跳过

        picks.append({
            "code": code,
            "score": score,
            "close": round(close, 2),
            "morningstar": round(ms_value, 2),
            "discount_pct": discount,
            "tide": dow["tide"],
            "wave": dow["wave"],
            "ripple_rsi": dow["ripple"].get("rsi12"),
            "signal": dow["signal"],
            "trade_hint": dow["trade_hint"],
        })

    # 按折扣率降序（最便宜的排前面）
    picks.sort(key=lambda x: -x["discount_pct"])

    return {
        "date": date,
        "total": len(picks),
        "picks": picks,
    }


@app.get("/api/content-generator")
def get_content_generator(
    code: str = Query(..., description="标的代码，如 US.AVGO"),
    platform: str | None = Query(default=None, description="平台：xiaohongshu/zhihu/gongzhonghao，不传返回全部"),
    date: str | None = Query(default=None, description="评分日期 YYYY-MM-DD，不传取最新"),
):
    """生成自媒体发布文案（小红书/知乎/公众号），基于该标的的道氏趋势 + 估值信号。"""
    from trader_analysis.futu_strategy.content_generator import generate, generate_single
    from trader_analysis.futu_strategy.technical_analysis import analyze_dow_trend

    conn = storage._get_conn()

    w = conn.execute(
        "SELECT name, morningstar_fair_value, analyst_target_mean FROM watchlist WHERE code = ?",
        (code,),
    ).fetchone()
    if not w:
        conn.close()
        return {"data": None, "message": f"标的 {code} 不在标的池"}

    name = w["name"] or ""
    ms_value = float(w["morningstar_fair_value"]) if w["morningstar_fair_value"] else None
    analyst_target = float(w["analyst_target_mean"]) if w["analyst_target_mean"] else None

    if date:
        s = conn.execute(
            "SELECT total_score FROM score_results WHERE code = ? AND date = ?", (code, date)
        ).fetchone()
    else:
        s = conn.execute(
            "SELECT total_score, date FROM score_results WHERE code = ? ORDER BY date DESC LIMIT 1", (code,)
        ).fetchone()
    conn.close()

    if not s:
        return {"data": None, "message": f"{code} 暂无评分数据"}

    score = s["total_score"]
    score_date = date or str(s["date"])

    daily_df = storage.query_recent(code, "1d", limit=120)
    weekly_df = storage.query_recent(code, "1w", limit=60)
    if daily_df.empty or len(daily_df) < 20:
        return {"data": None, "message": f"{code} 数据不足"}

    close = float(daily_df.iloc[-1]["close"])
    if close <= 0:
        return {"data": None, "message": f"{code} 收盘价异常"}

    dow = analyze_dow_trend(daily_df, weekly_df, ms_value, close)

    discount = round((ms_value - close) / close * 100, 1) if ms_value and close else None
    pick = {
        "code": code,
        "date": score_date,
        "score": score,
        "close": round(close, 2),
        "morningstar": round(ms_value, 2) if ms_value else None,
        "discount_pct": discount,
        "tide": dow["tide"],
        "wave": dow["wave"],
        "ripple_rsi": dow["ripple"].get("rsi12"),
        "signal": dow["signal"],
        "trade_hint": dow["trade_hint"],
    }

    if platform:
        content = generate_single(pick, platform, name, analyst_target)
        return {"code": code, "date": score_date, "content": content}
    return {"code": code, "date": score_date, "content": generate(pick, name, analyst_target)}


@app.get("/api/fundamental")
def get_fundamental(
    code: str,
    date: str | None = Query(default=None, description="指定日期 YYYY-MM-DD，不传取最新"),
):
    """返回分析师目标价、晨星公允价值等基本面估值数据（V2 — 支持日期筛选）。"""
    conn = storage._get_conn()
    try:
        row = conn.execute(
            "SELECT analyst_target_mean, morningstar_fair_value, current_price, "
            "forward_pe, peg_ratio, roe, market_cap "
            "FROM watchlist WHERE code = ?",
            (code,),
        ).fetchone()
        if not row:
            conn.close()
            return {"data": None, "message": f"{code} 暂无基本面数据"}

        # 按日期取收盘价，不传日期取最新
        if date:
            kline = conn.execute(
                "SELECT close FROM kline_indicators WHERE code=? AND ktype='1d' AND date<=? "
                "ORDER BY date DESC LIMIT 1",
                (code, date),
            ).fetchone()
        else:
            kline = conn.execute(
                "SELECT close FROM kline_indicators WHERE code=? AND ktype='1d' ORDER BY date DESC LIMIT 1",
                (code,),
            ).fetchone()

        current = float(kline["close"]) if kline and kline["close"] else None
        if current is None and row["current_price"]:
            current = float(row["current_price"])
        if current is None:
            conn.close()
            return {"data": None, "message": f"{code} 暂无价格数据"}
        analyst = float(row["analyst_target_mean"]) if row["analyst_target_mean"] else None
        morningstar = float(row["morningstar_fair_value"]) if row["morningstar_fair_value"] else None

        return {
            "code": code,
            "current_price": round(current, 2),
            "analyst_target": round(analyst, 2) if analyst else None,
            "analyst_upside_pct": round((analyst - current) / current * 100, 1) if analyst else None,
            "morningstar_value": round(morningstar, 2) if morningstar else None,
            "morningstar_discount_pct": round((morningstar - current) / current * 100, 1) if morningstar else None,
            "forward_pe": round(row["forward_pe"], 1) if row["forward_pe"] else None,
            "peg_ratio": round(row["peg_ratio"], 2) if row["peg_ratio"] else None,
            "roe": round(row["roe"], 1) if row["roe"] else None,
            "market_cap": round(row["market_cap"], 0) if row["market_cap"] else None,
        }
    finally:
        conn.close()
