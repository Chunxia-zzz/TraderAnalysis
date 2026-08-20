"""CLI 入口。

提供 serve / init / update / run 四个命令，统一管理策略系统的各项操作。
"""

from __future__ import annotations

from typing import Optional

import typer
import uvicorn

app = typer.Typer(
    add_completion=False,
    help="Futu 量化评分与模拟盘交易系统。",
)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="监听地址"),
    port: int = typer.Option(8000, help="监听端口"),
) -> None:
    """启动 FastAPI 服务，供前端消费指标和评分数据。"""
    uvicorn.run("trader_analysis.futu_strategy.api_server:app", host=host, port=port, reload=True)


@app.command()
def init(
    codes: Optional[list[str]] = typer.Option(None, help="标的代码列表（默认全部 watchlist）"),
    force: bool = typer.Option(False, help="强制重新拉取，忽略已有数据"),
    start: Optional[str] = typer.Option(None, help="起始日期 YYYY-MM-DD，拉取更长历史（如 2022-06-01）"),
) -> None:
    """拉取历史 K 线并计算指标，写入数据库。支持断点续传。"""
    from trader_analysis.futu_strategy import config
    from trader_analysis.futu_strategy.init_history import run_init

    code_list = codes if codes else config.WATCHLIST
    run_init(code_list, force=force, start=start)


@app.command()
def update(
    codes: Optional[list[str]] = typer.Option(None, help="标的代码列表（默认全部 watchlist）"),
) -> None:
    """增量更新 K 线和指标（每日收盘后运行）。"""
    from trader_analysis.futu_strategy import config
    from trader_analysis.futu_strategy.daily_update import run_update

    code_list = codes if codes else config.WATCHLIST
    run_update(code_list)


@app.command()
def run(
    codes: Optional[list[str]] = typer.Option(None, help="标的代码列表（默认全部 watchlist）"),
) -> None:
    """运行完整策略流程：增量更新 → 评分 → 交易。"""
    from trader_analysis.futu_strategy import config
    from trader_analysis.futu_strategy.runner import run_strategy

    code_list = codes if codes else config.WATCHLIST
    run_strategy(code_list)


@app.command()
def score(
    codes: Optional[list[str]] = typer.Option(None, help="标的代码列表（默认全部 watchlist）"),
    backfill: int = typer.Option(0, help="回溯天数（从已有K线数据回溯计算历史评分，0=仅计算最新）"),
) -> None:
    """纯本地评分：从 DB 读取指标，计算个股评分并写入 score_results。不依赖 OpenD。"""
    from datetime import date, timedelta

    from trader_analysis.futu_strategy import config
    from trader_analysis.futu_strategy.scorer import calculate_score
    from trader_analysis.futu_strategy.storage import (
        init_db,
        query_latest_score,
        query_recent,
        upsert_score,
    )

    init_db()
    code_list = codes if codes else config.WATCHLIST

    # 读取大盘温度历史（用于恐慌加成）
    import sqlite3

    db_path = config.DB_PATH
    _conn = sqlite3.connect(db_path)
    market_temps = dict(_conn.execute("SELECT date, composite_score FROM market_score").fetchall())
    _conn.close()

    if backfill > 0:
        typer.echo(f"回溯 {backfill} 天，{len(code_list)} 个标的...")
        total_written = 0
        for code in code_list:
            daily_all = query_recent(code, "1d", limit=backfill + 300)
            weekly_all = query_recent(code, "1w", limit=500)
            if daily_all.empty or weekly_all.empty or len(daily_all) < 60:
                continue
            total_rows = len(daily_all)
            fill_count = min(backfill, total_rows - 60)
            for i in range(fill_count, 0, -1):
                end_idx = total_rows - i + 1
                daily_slice = daily_all.iloc[:end_idx]
                score_date = str(daily_slice.iloc[-1].get("date", ""))
                weekly_slice = weekly_all[weekly_all["date"] <= score_date]
                if weekly_slice.empty:
                    continue
                try:
                    mc = market_temps.get(score_date)
                    result = calculate_score(code, daily_slice, weekly_slice, market_composite=mc)
                    upsert_score(code, score_date, result)
                    total_written += 1
                except Exception:
                    pass
        typer.echo(f"回溯完成，写入 {total_written} 条评分")
    else:
        # 自动增量补算：补算「上次评分之后」缺失的交易日评分，而非只算最新一天
        # 场景：上次 update 是 8/12，今天 8/20 才跑，则补算 8/13~8/19 所有交易日的评分
        scored, skipped = 0, 0
        for code in code_list:
            daily_all = query_recent(code, "1d", limit=300)
            weekly_all = query_recent(code, "1w", limit=60)
            if daily_all.empty or weekly_all.empty:
                skipped += 1
                continue

            kline_latest = str(daily_all.iloc[-1].get("date", ""))
            latest = query_latest_score(code)
            latest_score_date = latest.get("date") if latest else None

            if latest_score_date is None:
                # 从未评分过，只算最新一天
                pending_dates = [kline_latest]
            elif kline_latest > latest_score_date:
                # 有缺口：补算 (latest_score_date, kline_latest] 之间所有交易日
                pending_dates = [str(d) for d in daily_all["date"] if str(d) > latest_score_date]
            else:
                # 已是最新，重算最新一天（幂等）
                pending_dates = [kline_latest]

            for score_date in pending_dates:
                daily_slice = daily_all[daily_all["date"] <= score_date]
                weekly_slice = weekly_all[weekly_all["date"] <= score_date]
                if weekly_slice.empty:
                    continue
                try:
                    mc = market_temps.get(score_date)
                    result = calculate_score(code, daily_slice, weekly_slice, market_composite=mc)
                    upsert_score(code, score_date, result)
                    scored += 1
                    if result["signal"] != "NO_ACTION":
                        typer.echo(f"  {code}: {result['total_score']}分 → {result['signal']} ({score_date})")
                except Exception:
                    pass
        typer.echo(f"评分完成：写入 {scored} 条评分，跳过 {skipped} 个标的（无数据）")


@app.command()
def migrate_watchlist(
    dry: bool = typer.Option(False, help="预览模式，不实际写入"),
) -> None:
    """从 watchlist.json 迁移到 SQLite（一次性操作）。"""
    from trader_analysis.futu_strategy import config
    from trader_analysis.futu_strategy.watchlist_storage import (
        init_watchlist_table,
        migrate_from_json,
        watchlist_count,
    )

    init_watchlist_table()
    existing = watchlist_count()
    if existing > 0:
        typer.echo(f"watchlist 表已有 {existing} 条记录。")
        typer.echo("如需重新导入，请先清空表或手动删除相关记录。")
        return

    items, categories = config._load_watchlist()
    typer.echo(f"从 watchlist.json 读取 {len(items)} 条记录")

    if dry:
        for item in items:
            code = f"{item['market']}.{item['ticker']}"
            typer.echo(f"  [DRY] {code} — {item['name']} ({item['category']})")
        typer.echo(f"\n预览完成，共 {len(items)} 条。去掉 --dry 执行实际导入。")
        return

    count = migrate_from_json(items, categories)
    typer.echo(f"迁移完成，写入 {count} 条记录。")


@app.command()
def refresh_snapshot(
    codes: Optional[list[str]] = typer.Option(None, help="指定代码，不传则全部刷新"),
) -> None:
    """刷新标的池静态快照字段（trailing_pe, market_cap 等）。需要 OpenD。"""
    from trader_analysis.futu_strategy.stock_info_fetcher import fetch_snapshot_batch
    from trader_analysis.futu_strategy.watchlist_storage import (
        get_all_codes,
        init_watchlist_table,
        refresh_snapshot as _refresh,
    )

    init_watchlist_table()
    code_list = codes if codes else get_all_codes()
    typer.echo(f"刷新 {len(code_list)} 只标的的快照数据...")

    snapshots = fetch_snapshot_batch(code_list)
    updated = 0
    for c in code_list:
        if c in snapshots:
            _refresh(c, snapshots[c])
            updated += 1

    typer.echo(f"刷新完成：成功 {updated}，失败 {len(code_list) - updated}")


@app.command()
def fundamental(
    codes: Optional[list[str]] = typer.Option(None, help="标的代码列表（默认全部 watchlist）"),
) -> None:
    """拉取基本面数据并评分（数据源：yfinance，不依赖 OpenD）。

    注意：yfinance 数据源在中国大陆可能无法访问，导致 forward_pe 等字段大量缺失。
    估值折价建议改用晨星公允价值 + 分析师目标价（通过 scripts/fetch_fundamental_targets.py 更新，
    已写入 watchlist 表的 morningstar_fair_value / analyst_target_mean 字段）。
    """
    from datetime import date

    from trader_analysis.futu_strategy import config
    from trader_analysis.futu_strategy.fundamental_fetcher import fetch_all
    from trader_analysis.futu_strategy.fundamental_scorer import calculate_fundamental_score
    from trader_analysis.futu_strategy.storage import init_db, upsert_fundamental
    from trader_analysis.futu_strategy.watchlist_storage import init_watchlist_table, update_stock

    init_db()
    init_watchlist_table()

    code_list = codes if codes else config.get_watchlist()
    typer.echo(f"拉取基本面数据中... ({len(code_list)} 只标的)")

    results = fetch_all(code_list)
    typer.echo(f"完成：{len(results)} 只成功，{len(code_list) - len(results)} 只跳过（ETF/无数据）")

    today = date.today().isoformat()
    undervalued = []
    overvalued = []

    for item in results:
        code = item["code"]
        data = item["data"]

        # 评分
        score_result = calculate_fundamental_score(code, data)
        # 合并数据 + 评分结果
        full_record = {**data, **score_result}
        upsert_fundamental(code, today, full_record)

        # 同步关键字段到 watchlist 表
        sync_fields = {}
        for src, dst in [
            ("forward_pe", "forward_pe"), ("forward_eps", "forward_eps"),
            ("peg_ratio", "peg_ratio"), ("revenue_growth", "revenue_growth"),
            ("earnings_growth", "earnings_growth"), ("profit_margin", "profit_margin"),
            ("roe", "roe"), ("debt_to_equity", "debt_to_equity"),
        ]:
            if data.get(src) is not None:
                sync_fields[dst] = data[src]
        if sync_fields:
            update_stock(code, sync_fields)

        # 同步快照字段
        from trader_analysis.futu_strategy.watchlist_storage import refresh_snapshot
        snapshot = {}
        for f in ["trailing_pe", "market_cap", "current_price", "dividend_yield", "beta"]:
            if data.get(f) is not None:
                snapshot[f] = data[f]
        if snapshot:
            refresh_snapshot(code, snapshot)

        # 收集输出
        signal = score_result["valuation_signal"]
        if signal == "UNDERVALUED":
            undervalued.append((code, score_result["fundamental_score"], data.get("forward_pe"), data.get("recommendation")))
        elif signal == "OVERVALUED":
            overvalued.append((code, score_result["fundamental_score"], data.get("forward_pe"), data.get("recommendation")))

    # 打印摘要
    typer.echo("")
    typer.echo("── 基本面评分 ──")
    if undervalued:
        typer.echo(f"  UNDERVALUED ({len(undervalued)}只):")
        for code, score, fpe, rec in sorted(undervalued, key=lambda x: -x[1]):
            fpe_str = f"FPE={fpe:.1f}x" if fpe else "FPE=N/A"
            typer.echo(f"    {code:12s} {score:.1f}分  {fpe_str}  {rec or ''}")
    if overvalued:
        typer.echo(f"  OVERVALUED ({len(overvalued)}只):")
        for code, score, fpe, rec in sorted(overvalued, key=lambda x: -x[1]):
            fpe_str = f"FPE={fpe:.1f}x" if fpe else "FPE=N/A"
            typer.echo(f"    {code:12s} {score:.1f}分  {fpe_str}  {rec or ''}")


@app.command()
def create_admin(
    username: str = typer.Option("admin", help="管理员用户名"),
    password: str = typer.Option(
        ..., prompt=True, hide_input=True, confirmation_prompt=True, help="管理员密码"
    ),
) -> None:
    """创建管理员账号（首次部署时使用）。"""
    from trader_analysis.futu_strategy.auth import hash_password
    from trader_analysis.futu_strategy.auth_storage import create_user, init_users_table, user_exists

    init_users_table()
    if user_exists(username):
        typer.echo(f"Error: User '{username}' already exists.", err=True)
        raise typer.Exit(code=1)

    hashed = hash_password(password)
    create_user(username, hashed, role="admin")
    typer.echo(f"Admin account '{username}' created successfully.")


@app.command()
def temperature(
    backfill: int = typer.Option(0, help="回溯天数（从已有K线数据计算历史评分，0=仅计算最新）"),
) -> None:
    """计算市场温度评分（6 维度综合评分 + 目标仓位建议）。"""
    from trader_analysis.futu_strategy.market_scorer import (
        backfill_market_temperature,
        calculate_market_temperature,
    )
    from trader_analysis.futu_strategy.storage import init_db

    init_db()

    if backfill > 0:
        typer.echo(f"回溯计算最近 {backfill} 天的市场温度...")
        count = backfill_market_temperature(days=backfill)
        typer.echo(f"回溯完成，写入 {count} 天评分")
        typer.echo("")

    result = calculate_market_temperature()

    typer.echo(f"日期: {result['date']}")
    typer.echo(f"综合评分: {result['composite_score']:.1f} / 100")
    typer.echo(f"市场状态: {result['market_status']}")
    typer.echo(f"建议仓位: {result['target_position_pct']:.1f}%")
    typer.echo(f"操作建议: {result['action_suggestion']}")
    if result["extreme_triggered"]:
        typer.echo(f"[极端层已触发] 杠杆工具: {result['leverage_tool']}")
    typer.echo("── 维度拆解 ──")
    for dim in result["dimensions"]:
        typer.echo(f"  {dim['label']:6s} [{dim['weight']:.0%}]  {dim['score']:.1f}")


@app.command()
def backtest(
    code: str = typer.Argument(..., help="股票代码 (Futu 格式, 如 US.SNDK)"),
    mode: str = typer.Option("hold", help="策略模式: hold(买入持有) / swing(波段操作) / trend(趋势跟踪)"),
    threshold: int = typer.Option(40, help="买入评分阈值 (1-100)"),
    holding_days: int = typer.Option(10, "--holding-days", help="[hold] 持有交易日数"),
    exit_threshold: int = typer.Option(30, "--exit-threshold", help="[swing] 评分回落卖出阈值"),
    max_holding_days: int = typer.Option(120, "--max-holding-days", help="[swing/trend] 最大持有天数"),
    trail_ma: str = typer.Option("ma5", "--trail-ma", help="[trend] 跟踪止盈均线: ma5/ma10/ma20"),
    entry_confirm: str = typer.Option("none", "--entry-confirm", help="买入确认: none(立即) / above_ma5(站上MA5再买)"),
    cooldown: str = typer.Option("holding", help="去重策略: none/holding/custom"),
    cooldown_days: int = typer.Option(None, "--cooldown-days", help="custom 模式冷却天数"),
    start_date: Optional[str] = typer.Option(None, "--start-date", help="起始日期 YYYY-MM-DD"),
    end_date: Optional[str] = typer.Option(None, "--end-date", help="截止日期 YYYY-MM-DD"),
) -> None:
    """信号回测：验证评分信号的历史收益表现。支持 hold/swing 两种模式。"""
    from trader_analysis.futu_strategy.backtest import BacktestParams, run_backtest
    from trader_analysis.futu_strategy.storage import init_db

    init_db()

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

    result = run_backtest(params)

    # 无数据
    if "data" in result and result["data"] is None:
        typer.echo(result["message"])
        raise typer.Exit(code=1)

    # 输出参数
    p = result["params"]
    typer.echo(f"\nSignal Backtest: {result['code']} [{p['mode']}]")
    typer.echo("━" * 56)
    if p["mode"] == "swing":
        typer.echo(f"Parameters: buy≥{p['threshold']}, sell≤{p['exit_threshold']}, max_hold={p['max_holding_days']}d, cooldown={p['cooldown']}")
    elif p["mode"] == "trend":
        typer.echo(f"Parameters: buy≥{p['threshold']}, trail={p['trail_ma']}, max_hold={p['max_holding_days']}d, cooldown={p['cooldown']}")
    else:
        typer.echo(f"Parameters: threshold={p['threshold']}, holding={p['holding_days']}d, cooldown={p['cooldown']}")
    typer.echo(f"Date Range: {p['start_date']} → {p['end_date']}")

    # 输出汇总
    s = result["summary"]
    typer.echo(f"\nSummary:")
    typer.echo(f"  Signals triggered:   {s['total_signals']}")
    typer.echo(f"  Completed trades:    {s['completed_trades']}")
    typer.echo(f"  Win rate:            {s['win_rate']:.1f}%  ({s['win_count']}W / {s['loss_count']}L)")
    typer.echo(f"  Avg return:          {s['avg_return_pct']:+.2f}%")
    typer.echo(f"  Median return:       {s['median_return_pct']:+.2f}%")
    typer.echo(f"  Best / Worst:        {s['max_return_pct']:+.2f}% / {s['min_return_pct']:+.2f}%")
    typer.echo(f"  Total return:        {s['total_return_pct']:+.2f}%")
    typer.echo(f"  Profit factor:       {s['profit_factor']:.2f}")
    typer.echo(f"  Sharpe-like:         {s['sharpe_like']:.2f}")

    # 输出平均持有天数（swing 模式有意义）
    if result.get("mode") == "swing" and s.get("avg_holding_days"):
        typer.echo(f"  Avg holding days:    {s['avg_holding_days']:.1f}")

    # 输出最近交易
    trades = result["trades"]
    completed = [t for t in trades if t["status"] == "complete"]
    recent = completed[-10:] if len(completed) > 10 else completed
    if recent:
        typer.echo(f"\nRecent Trades (last {len(recent)}):")
        typer.echo(f"  {'Date':>10}  {'Entry':>8}  {'Exit Date':>10}  {'Exit':>8}  {'Return':>8}  {'Days':>4}  {'Reason':>10}")
        typer.echo(f"  {'-'*10}  {'-'*8}  {'-'*10}  {'-'*8}  {'-'*8}  {'-'*4}  {'-'*10}")
        for t in recent:
            days_str = f"{t['holding_days']:>4}" if t.get("holding_days") else "   -"
            reason = t.get("exit_reason", "")[:10] if t.get("exit_reason") else ""
            typer.echo(
                f"  {t['signal_date']:>10}  {t['entry_price']:>8.2f}  "
                f"{t['exit_date']:>10}  {t['exit_price']:>8.2f}  "
                f"{t['return_pct']:>+7.2f}%  {days_str}  {reason:>10}"
            )


# ── 网格交易命令 ──────────────────────────────────────────────────────────────


@app.command("grid-create")
def grid_create(
    code: str = typer.Option(..., help="标的代码 (US.GLD)"),
    upper: float = typer.Option(..., help="网格上界"),
    lower: float = typer.Option(..., help="网格下界"),
    grid_count: int = typer.Option(10, help="网格数量"),
    order_qty: int = typer.Option(10, "--order-qty", help="每格下单股数"),
    max_position: int = typer.Option(100, "--max-position", help="最大持仓股数"),
    env: str = typer.Option("simulate", help="环境: simulate/live"),
    name: str = typer.Option("", help="配置名称"),
    daily_loss_limit: float = typer.Option(-500.0, "--daily-loss-limit", help="单日最大亏损(美元)"),
) -> None:
    """创建网格交易配置。"""
    from trader_analysis.futu_strategy.grid_trader.state_manager import create_config, init_grid_tables

    if upper <= lower:
        typer.echo("Error: upper must be greater than lower", err=True)
        raise typer.Exit(code=1)

    init_grid_tables()
    config_id = create_config(
        code=code,
        price_upper=upper,
        price_lower=lower,
        grid_count=grid_count,
        order_qty=order_qty,
        max_position=max_position,
        env=env,
        name=name,
        daily_loss_limit=daily_loss_limit,
    )
    spacing = (upper - lower) / grid_count
    typer.echo(f"Grid config #{config_id} created.")
    typer.echo(f"  Code: {code} | Env: {env}")
    typer.echo(f"  Range: ${lower:.2f} - ${upper:.2f} | Grids: {grid_count} | Spacing: ${spacing:.2f}")
    typer.echo(f"  Order qty: {order_qty} | Max position: {max_position}")
    typer.echo(f"\nStart with: trader-analysis grid-start {config_id}")


@app.command("grid-start")
def grid_start(
    config_id: int = typer.Argument(..., help="网格配置 ID"),
) -> None:
    """启动网格交易引擎（长驻进程，Ctrl+C 停止）。"""
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from trader_analysis.futu_strategy.grid_trader.engine import GridEngine
    from trader_analysis.futu_strategy.grid_trader.state_manager import get_config, init_grid_tables

    init_grid_tables()
    cfg = get_config(config_id)
    if not cfg:
        typer.echo(f"Error: Grid config #{config_id} not found", err=True)
        raise typer.Exit(code=1)

    if cfg.env == "live":
        confirm = typer.confirm("LIVE TRADING MODE - Real money at risk. Continue?")
        if not confirm:
            raise typer.Exit()

    engine = GridEngine(config_id)
    engine.start()


@app.command("grid-stop")
def grid_stop(
    config_id: int = typer.Argument(..., help="网格配置 ID"),
) -> None:
    """停止网格交易引擎（发送停止信号）。"""
    from trader_analysis.futu_strategy.grid_trader.state_manager import get_config, init_grid_tables, update_config_status

    init_grid_tables()
    cfg = get_config(config_id)
    if not cfg:
        typer.echo(f"Error: Grid config #{config_id} not found", err=True)
        raise typer.Exit(code=1)

    update_config_status(config_id, "stopped")
    typer.echo(f"Grid #{config_id} stop signal sent. Engine will exit on next cycle.")


@app.command("scan-top")
def scan_top(
    codes: Optional[list[str]] = typer.Option(None, help="标的代码列表（默认全部 watchlist）"),
    min_strength: float = typer.Option(0.3, "--min-strength", help="信号强度过滤阈值 0~1"),
) -> None:
    """扫描顶背离预警信号：对所有标的执行顶部信号检测，打印摘要并写入 DB。不依赖 OpenD。"""
    from datetime import date

    from trader_analysis.futu_strategy import config
    from trader_analysis.futu_strategy.storage import init_db, insert_top_signal, query_recent
    from trader_analysis.futu_strategy.top_detector import detect_all

    init_db()
    code_list = codes if codes else config.WATCHLIST
    today = date.today().isoformat()

    typer.echo(f"扫描顶背离信号中... ({len(code_list)} 只标的，日期={today})")
    typer.echo("")

    triggered: list[tuple[str, list]] = []

    for code in code_list:
        daily_df = query_recent(code, "1d", limit=300)
        if daily_df.empty or len(daily_df) < 30:
            continue

        signals = detect_all(daily_df)
        if not signals:
            continue

        strong_signals = [s for s in signals if s.strength >= min_strength]
        if not strong_signals:
            continue

        triggered.append((code, strong_signals))

        # 写入 DB
        for sig in strong_signals:
            try:
                insert_top_signal(code, today, sig.signal_type, sig.strength, sig.detail)
            except Exception:
                pass

    if not triggered:
        typer.echo("无顶背离信号触发。")
        return

    typer.echo(f"── 顶背离预警 ({len(triggered)} 只标的) ──")
    for code, signals in triggered:
        sig_summary = ", ".join(f"{s.signal_type}({s.strength:.2f})" for s in signals)
        typer.echo(f"  {code:14s}  {sig_summary}")

    typer.echo("")
    typer.echo(f"信号已写入 DB（top_signal_log 表），可通过 /api/top-signals 查询。")


@app.command("scan-signals")
def scan_signals(
    codes: Optional[list[str]] = typer.Option(None, help="标的代码列表（默认全部 watchlist）"),
    backfill: int = typer.Option(0, help="回溯天数（从已有K线数据回溯计算历史信号，0=仅计算最新）"),
) -> None:
    """扫描交易信号（顶部+底部），写入 DB。支持 --backfill 回溯历史。不依赖 OpenD。"""
    from datetime import date

    from trader_analysis.futu_strategy import config
    from trader_analysis.futu_strategy.bottom_detector import detect_all as detect_all_bottom
    from trader_analysis.futu_strategy.storage import (
        init_db, insert_bottom_signal, insert_top_signal, query_recent,
    )
    from trader_analysis.futu_strategy.top_detector import detect_all as detect_all_top

    init_db()
    code_list = codes if codes else config.WATCHLIST

    if backfill > 0:
        from trader_analysis.futu_strategy.ema_cross_detector import detect_ema_cross

        typer.echo(f"回溯 {backfill} 天，{len(code_list)} 个标的...")
        total_top = 0
        total_bottom = 0
        total_ema = 0

        for code in code_list:
            daily_all = query_recent(code, "1d", limit=backfill + 300)
            if daily_all.empty or len(daily_all) < 60:
                continue

            # 4H 数据（用于 EMA 交叉回溯）
            four_h_all = query_recent(code, "4h", limit=backfill * 2 + 100)

            total_rows = len(daily_all)
            fill_count = min(backfill, total_rows - 30)

            for i in range(fill_count, 0, -1):
                end_idx = total_rows - i + 1
                daily_slice = daily_all.iloc[:end_idx]
                signal_date = str(daily_slice.iloc[-1].get("date", ""))

                top_sigs = detect_all_top(daily_slice)
                for sig in top_sigs:
                    try:
                        insert_top_signal(code, signal_date, sig.signal_type, sig.strength, sig.detail)
                        total_top += 1
                    except Exception:
                        pass

                bottom_sigs = detect_all_bottom(daily_slice)
                for sig in bottom_sigs:
                    try:
                        insert_bottom_signal(code, signal_date, sig.signal_type, sig.strength, sig.detail)
                        total_bottom += 1
                    except Exception:
                        pass

                # EMA 交叉 — 日线
                ema_sigs_1d = detect_ema_cross(daily_slice, timeframe="1d")
                for sig in ema_sigs_1d:
                    try:
                        if "BULL" in sig.signal_type:
                            insert_bottom_signal(code, signal_date, sig.signal_type, sig.strength, sig.detail)
                        else:
                            insert_top_signal(code, signal_date, sig.signal_type, sig.strength, sig.detail)
                        total_ema += 1
                    except Exception:
                        pass

                # EMA 交叉 — 4H（找到该日期对应的最后一根 4H K 线位置）
                if not four_h_all.empty and len(four_h_all) >= 2:
                    # 4H date 格式为 "YYYY-MM-DD HH:MM:SS"，截取日期部分匹配
                    mask = four_h_all["date"].str[:10] <= signal_date
                    four_h_slice = four_h_all[mask]
                    if len(four_h_slice) >= 2:
                        ema_sigs_4h = detect_ema_cross(four_h_slice, timeframe="4h")
                        for sig in ema_sigs_4h:
                            try:
                                if "BULL" in sig.signal_type:
                                    insert_bottom_signal(code, signal_date, sig.signal_type, sig.strength, sig.detail)
                                else:
                                    insert_top_signal(code, signal_date, sig.signal_type, sig.strength, sig.detail)
                                total_ema += 1
                            except Exception:
                                pass

        typer.echo(f"回溯完成，写入 {total_top} 条顶部信号，{total_bottom} 条底部信号，{total_ema} 条EMA交叉信号。")
        return

    # 自动增量补算：补算「上次信号扫描之后」缺失的交易日信号
    typer.echo(f"扫描交易信号中... ({len(code_list)} 只标的)")

    from trader_analysis.futu_strategy.ema_cross_detector import detect_ema_cross

    import sqlite3 as _sqlite3

    top_count = 0
    bottom_count = 0
    ema_count = 0
    for code in code_list:
        daily_all = query_recent(code, "1d", limit=300)
        if daily_all.empty or len(daily_all) < 30:
            continue

        four_h_all = query_recent(code, "4h", limit=120)

        kline_latest = str(daily_all.iloc[-1].get("date", ""))

        # 查该标的信号表最新日期（顶部 + 底部取更晚者）
        _conn = _sqlite3.connect(config.DB_PATH)
        _r1 = _conn.execute("SELECT MAX(date) FROM top_signal_log WHERE code = ?", (code,)).fetchone()
        _r2 = _conn.execute("SELECT MAX(date) FROM bottom_signal_log WHERE code = ?", (code,)).fetchone()
        _conn.close()
        _latest_dates = [d for d in (_r1[0], _r2[0]) if d]
        latest_signal_date = max(_latest_dates) if _latest_dates else None

        if latest_signal_date is None:
            pending_dates = [kline_latest]
        elif kline_latest > latest_signal_date:
            pending_dates = [str(d) for d in daily_all["date"] if str(d) > latest_signal_date]
        else:
            pending_dates = [kline_latest]

        for signal_date in pending_dates:
            daily_slice = daily_all[daily_all["date"] <= signal_date]
            if len(daily_slice) < 30:
                continue

            top_sigs = detect_all_top(daily_slice)
            for sig in top_sigs:
                try:
                    insert_top_signal(code, signal_date, sig.signal_type, sig.strength, sig.detail)
                    top_count += 1
                except Exception:
                    pass

            bottom_sigs = detect_all_bottom(daily_slice)
            for sig in bottom_sigs:
                try:
                    insert_bottom_signal(code, signal_date, sig.signal_type, sig.strength, sig.detail)
                    bottom_count += 1
                except Exception:
                    pass

            # EMA 交叉信号 — 日线维度
            ema_sigs_1d = detect_ema_cross(daily_slice, timeframe="1d")
            for sig in ema_sigs_1d:
                try:
                    if "BULL" in sig.signal_type:
                        insert_bottom_signal(code, signal_date, sig.signal_type, sig.strength, sig.detail)
                    else:
                        insert_top_signal(code, signal_date, sig.signal_type, sig.strength, sig.detail)
                    ema_count += 1
                except Exception:
                    pass

            # EMA 交叉信号 — 4H 维度（找到该日期对应的最后一根 4H K 线位置）
            if not four_h_all.empty and len(four_h_all) >= 2:
                mask = four_h_all["date"].str[:10] <= signal_date
                four_h_slice = four_h_all[mask]
                if len(four_h_slice) >= 2:
                    ema_sigs_4h = detect_ema_cross(four_h_slice, timeframe="4h")
                    for sig in ema_sigs_4h:
                        try:
                            if "BULL" in sig.signal_type:
                                insert_bottom_signal(code, signal_date, sig.signal_type, sig.strength, sig.detail)
                            else:
                                insert_top_signal(code, signal_date, sig.signal_type, sig.strength, sig.detail)
                            ema_count += 1
                        except Exception:
                            pass

    typer.echo(f"完成，写入 {top_count} 条顶部信号，{bottom_count} 条底部信号，{ema_count} 条EMA交叉信号。")


@app.command("grid-status")
def grid_status(
    config_id: Optional[int] = typer.Argument(None, help="配置 ID（不传则显示全部）"),
) -> None:
    """查看网格交易运行状态。"""
    from trader_analysis.futu_strategy.grid_trader.state_manager import (
        get_config,
        get_state,
        init_grid_tables,
        list_configs,
    )
    from trader_analysis.futu_strategy.grid_trader.strategy import calculate_grid_lines

    init_grid_tables()

    if config_id is None:
        configs = list_configs()
        if not configs:
            typer.echo("No grid configs found. Create one with: trader-analysis grid-create")
            return
        for c in configs:
            typer.echo(f"  #{c['id']}: {c['code']} [{c['status'].upper()}] {c['env']} "
                       f"${c['price_lower']:.0f}-${c['price_upper']:.0f} x{c['grid_count']}")
        return

    cfg = get_config(config_id)
    if not cfg:
        typer.echo(f"Error: Grid config #{config_id} not found", err=True)
        raise typer.Exit(code=1)

    state = get_state(config_id)
    grid_lines = calculate_grid_lines(cfg)

    typer.echo(f"\nGrid #{cfg.id}: {cfg.code} [{cfg.status.upper()}] {cfg.env}")
    typer.echo(f"  Range: ${cfg.price_lower:.2f} - ${cfg.price_upper:.2f} | Spacing: ${cfg.grid_spacing:.2f}")
    if state.last_price:
        typer.echo(f"  Price: ${state.last_price:.2f} | Position: {state.current_position} shares | Cost: ${state.cost_basis:.2f}")
    else:
        typer.echo(f"  Price: N/A | Position: {state.current_position} shares")
    typer.echo(f"  Today: {state.daily_trades} trades | PnL: ${state.daily_pnl:+.2f}")

    # 网格可视化
    grid_vis = []
    for i in range(len(grid_lines)):
        s = state.grid_status.get(str(i), "empty")
        grid_vis.append("[B]" if s == "bought" else "[ ]")
    typer.echo(f"  Grid: {''.join(grid_vis)}")
