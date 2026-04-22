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
) -> None:
    """拉取历史 K 线并计算指标，写入数据库。支持断点续传。"""
    from trader_analysis.futu_strategy import config
    from trader_analysis.futu_strategy.init_history import run_init

    code_list = codes if codes else config.WATCHLIST
    run_init(code_list, force=force)


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
