"""一次性历史数据初始化脚本。

拉取所有标的的历史 K 线，计算全部指标，批量写入 SQLite。
仅在首次部署或需要重建数据库时运行。

用法：
    python -m trader_analysis.futu_strategy.init_history --codes HK.00700 US.AAPL
"""

from __future__ import annotations

import argparse
import logging

from trader_analysis.futu_strategy import config
from trader_analysis.futu_strategy.data_fetcher import check_kl_quota
from trader_analysis.futu_strategy.indicators import calc_indicators
from trader_analysis.futu_strategy.storage import batch_upsert, init_db

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def run_init(codes: list[str]) -> None:
    """对 codes 列表中每个标的执行历史数据初始化。"""
    try:
        from futu import OpenQuoteContext  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError("futu-api 未安装，请执行: pip install futu-api") from exc

    init_db()
    logger.info("数据库已初始化")

    quote_ctx = OpenQuoteContext(host=config.OPEND_HOST, port=config.OPEND_PORT)

    try:
        check_kl_quota(quote_ctx, codes)

        from trader_analysis.data.providers import FutuLiveDataProvider

        provider = FutuLiveDataProvider()

        for code in codes:
            try:
                logger.info(f"── 初始化 {code} ──")

                # 拉取日线（上限 1000 根）
                daily_df = provider.get_daily(
                    quote_ctx, code, count=config.INIT_DAILY_KLINE_COUNT
                )
                daily_df = calc_indicators(daily_df, config.DAILY_INDICATOR_CONFIG)
                n_daily = batch_upsert(code, "1d", daily_df)
                logger.info(f"  日线：{n_daily} 根已写入")

                # 拉取周线（上限 200 根）
                weekly_df = provider.get_weekly(
                    quote_ctx, code, count=config.INIT_WEEKLY_KLINE_COUNT
                )
                weekly_df = calc_indicators(weekly_df, config.WEEKLY_INDICATOR_CONFIG)
                n_weekly = batch_upsert(code, "1w", weekly_df)
                logger.info(f"  周线：{n_weekly} 根已写入")

            except Exception as exc:
                logger.error(f"  {code} 初始化失败：{exc}")

    finally:
        quote_ctx.close()
        logger.info("初始化完成，连接已关闭")


def main() -> None:
    parser = argparse.ArgumentParser(description="历史数据初始化")
    parser.add_argument(
        "--codes",
        nargs="+",
        default=config.WATCHLIST,
        metavar="CODE",
        help="标的代码列表（默认使用 config.WATCHLIST）",
    )
    args = parser.parse_args()
    run_init(args.codes)


if __name__ == "__main__":
    main()
