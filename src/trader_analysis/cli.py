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
    uvicorn.run("trader_analysis.futu_strategy.api_server:app", host=host, port=port, reload=False)


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
    from trader_analysis.futu_strategy.storage import init_db, query_recent, upsert_score

    init_db()
    code_list = codes if codes else config.WATCHLIST

    if backfill > 0:
        typer.echo(f"回溯 {backfill} 天，{len(code_list)} 个标的...")
        total_written = 0
        # 读取全量数据一次
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
                    result = calculate_score(code, daily_slice, weekly_slice)
                    upsert_score(code, score_date, result)
                    total_written += 1
                except Exception:
                    pass
        typer.echo(f"回溯完成，写入 {total_written} 条评分")
    else:
        today = date.today().isoformat()
        scored, skipped = 0, 0
        for code in code_list:
            daily_df = query_recent(code, "1d", limit=300)
            weekly_df = query_recent(code, "1w", limit=60)
            if daily_df.empty or weekly_df.empty:
                skipped += 1
                continue
            result = calculate_score(code, daily_df, weekly_df)
            score_date = str(daily_df.iloc[-1].get("date", today))
            upsert_score(code, score_date, result)
            scored += 1
            if result["signal"] != "NO_ACTION":
                typer.echo(f"  {code}: {result['total_score']}分 → {result['signal']}")
        typer.echo(f"评分完成：{scored} 个标的，跳过 {skipped} 个（无数据）")


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
