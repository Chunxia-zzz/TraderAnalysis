"""历史数据初始化脚本。

拉取标的池的历史 K 线，计算全部指标，批量写入 SQLite。
支持断点续传：已有数据的标的自动跳过，中断后重跑即可从断点继续。

用法：
    python -m trader_analysis.futu_strategy.init_history          # 拉取全部 watchlist
    python -m trader_analysis.futu_strategy.init_history --codes US.AAPL US.TSLA
    python -m trader_analysis.futu_strategy.init_history --force   # 强制重新拉取全部
"""

from __future__ import annotations

import argparse
import logging
import time

from trader_analysis.futu_strategy import config
from trader_analysis.futu_strategy.data_fetcher import check_kl_quota
from trader_analysis.futu_strategy.indicators import calc_indicators
from trader_analysis.futu_strategy.storage import batch_upsert, get_latest_date, init_db

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Futu API 频率限制：两次历史 K 线请求之间的最小间隔（秒）
_REQUEST_DELAY: float = 3.0


def _has_data(code: str) -> bool:
    """检查标的是否已有日线和周线数据。"""
    return get_latest_date(code, "1d") is not None and get_latest_date(code, "1w") is not None


def run_init(codes: list[str], *, force: bool = False, start: str | None = None) -> None:
    """对 codes 列表中每个标的执行历史数据初始化。

    Args:
        codes: 标的代码列表（Futu 格式）
        force: 为 True 时忽略已有数据，强制重新拉取
        start: 起始日期 "YYYY-MM-DD"，指定后按日期范围拉取（可获取更长历史）
    """
    try:
        from futu import OpenQuoteContext  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError("futu-api 未安装，请执行: pip install futu-api") from exc

    init_db()

    # ── 断点续传：过滤已有数据的标的 ──
    if not force:
        pending = [c for c in codes if not _has_data(c)]
        skipped = len(codes) - len(pending)
        if skipped:
            logger.info(f"跳过 {skipped} 个已有数据的标的")
        if not pending:
            logger.info("所有标的均已有数据，无需拉取（如需强制重建请加 --force）")
            return
    else:
        pending = list(codes)

    logger.info(f"待初始化：{len(pending)} 个标的" + (f"，起始日期：{start}" if start else ""))

    quote_ctx = OpenQuoteContext(host=config.OPEND_HOST, port=config.OPEND_PORT)

    try:
        check_kl_quota(quote_ctx, pending)

        from trader_analysis.futu_strategy.providers import FutuLiveDataProvider

        provider = FutuLiveDataProvider()
        success, failed = 0, 0

        for i, code in enumerate(pending, 1):
            try:
                logger.info(f"[{i}/{len(pending)}] 初始化 {code}")

                # 拉取日线
                daily_df = provider.get_daily(
                    quote_ctx, code, count=config.INIT_DAILY_KLINE_COUNT, start=start
                )
                daily_df = calc_indicators(daily_df, config.DAILY_INDICATOR_CONFIG)
                n_daily = batch_upsert(code, "1d", daily_df)
                logger.info(f"  日线：{n_daily} 根已写入")

                time.sleep(_REQUEST_DELAY)

                # 拉取周线
                weekly_df = provider.get_weekly(
                    quote_ctx, code, count=config.INIT_WEEKLY_KLINE_COUNT, start=start
                )
                weekly_df = calc_indicators(weekly_df, config.WEEKLY_INDICATOR_CONFIG)
                n_weekly = batch_upsert(code, "1w", weekly_df)
                logger.info(f"  周线：{n_weekly} 根已写入")

                success += 1

                # 非最后一个标的时，等待一下再请求下一个
                if i < len(pending):
                    time.sleep(_REQUEST_DELAY)

            except Exception as exc:
                failed += 1
                logger.error(f"  {code} 初始化失败：{exc}")

        logger.info(f"完成：成功 {success}，失败 {failed}，共 {len(pending)} 个")
        if failed:
            logger.info("失败的标的可重新运行此脚本，已成功的会自动跳过")

    finally:
        quote_ctx.close()
        logger.info("连接已关闭")


def main() -> None:
    parser = argparse.ArgumentParser(description="历史数据初始化")
    parser.add_argument(
        "--codes",
        nargs="+",
        default=config.WATCHLIST,
        metavar="CODE",
        help="标的代码列表（默认使用 watchlist.json 全部标的）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新拉取，忽略已有数据",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        metavar="YYYY-MM-DD",
        help="起始日期，指定后按日期范围拉取更长历史（如 2022-06-01）",
    )
    args = parser.parse_args()
    run_init(args.codes, force=args.force, start=args.start)


if __name__ == "__main__":
    main()
