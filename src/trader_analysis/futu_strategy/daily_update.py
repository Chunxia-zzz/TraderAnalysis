"""每日增量更新脚本。

查询各标的本地最新日期，只拉取新增 K 线，与历史数据拼接后重新计算末尾指标，
将新增行 UPSERT 到 SQLite。由定时任务或 runner.py 在评分前调用。

用法：
    python -m trader_analysis.futu_strategy.daily_update
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from trader_analysis.futu_strategy import config
from trader_analysis.futu_strategy.indicators import calc_indicators
from trader_analysis.futu_strategy.storage import (
    batch_upsert,
    get_latest_date,
    init_db,
    query_recent,
)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _update_ktype(
    quote_ctx,
    provider,
    code: str,
    ktype: str,
    indicator_config: dict,
    max_count: int,
) -> int:
    """更新单个标的的单个周期，返回新增行数。"""
    last_date = get_latest_date(code, ktype)
    if last_date is None:
        logger.warning(f"  {code}/{ktype} 本地无数据，请先运行 init_history.py")
        return 0

    # 根据周期选择拉取函数
    from futu import KLType  # type: ignore[import]

    kl_type = KLType.K_DAY if ktype == "1d" else KLType.K_WEEK
    new_df = provider.get_kline(
        quote_ctx, code, kl_type=kl_type, count=max_count, timeframe=ktype
    )

    # 统一列名为 date
    if "date" not in new_df.columns:
        if "timestamp" in new_df.columns:
            new_df = new_df.rename(columns={"timestamp": "date"})
        elif "time_key" in new_df.columns:
            new_df = new_df.rename(columns={"time_key": "date"})

    # 只保留比本地更新的行
    if "date" in new_df.columns:
        new_df["date"] = pd.to_datetime(new_df["date"]).dt.strftime("%Y-%m-%d")
        new_df = new_df[new_df["date"] > last_date]

    if new_df.empty:
        logger.info(f"  {code}/{ktype} 无新增数据")
        return 0

    # 读本地最近 300 根用于拼接
    history_df = query_recent(code, ktype, limit=300)

    # 拼接历史 + 新数据后统一计算指标
    merged = pd.concat([history_df, new_df], ignore_index=True)
    merged = merged.drop_duplicates(subset=["date"], keep="last")
    merged = merged.sort_values("date").reset_index(drop=True)
    merged = calc_indicators(merged, indicator_config)

    # 只取新增部分写入
    new_rows = merged[merged["date"] > last_date]
    if new_rows.empty:
        return 0

    count = batch_upsert(code, ktype, new_rows)
    logger.info(f"  {code}/{ktype} 新增 {count} 根")
    return count


def run_update(codes: list[str], quote_ctx=None) -> None:
    """对 codes 列表中每个标的执行增量更新。

    若 quote_ctx 为 None，则自行创建并在结束时关闭。
    """
    try:
        from futu import OpenQuoteContext  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError("futu-api 未安装，请执行: pip install futu-api") from exc

    init_db()

    own_ctx = quote_ctx is None
    if own_ctx:
        quote_ctx = OpenQuoteContext(host=config.OPEND_HOST, port=config.OPEND_PORT)

    try:
        from trader_analysis.futu_strategy.providers import FutuLiveDataProvider

        provider = FutuLiveDataProvider()

        import time as _time

        for idx, code in enumerate(codes):
            try:
                logger.info(f"── 增量更新 {code} ({idx+1}/{len(codes)}) ──")

                _update_ktype(
                    quote_ctx,
                    provider,
                    code,
                    "1d",
                    config.DAILY_INDICATOR_CONFIG,
                    config.DAILY_KLINE_COUNT,
                )
                _update_ktype(
                    quote_ctx,
                    provider,
                    code,
                    "1w",
                    config.WEEKLY_INDICATOR_CONFIG,
                    config.WEEKLY_KLINE_COUNT,
                )

            except Exception as exc:
                logger.error(f"  {code} 增量更新失败：{exc}")

            # Futu API 限频：每30秒60次，每个标的2次请求，留余量
            if idx < len(codes) - 1:
                _time.sleep(1.0)

    finally:
        if own_ctx:
            quote_ctx.close()
            logger.info("增量更新完成，连接已关闭")


def main() -> None:
    parser = argparse.ArgumentParser(description="每日增量更新")
    parser.add_argument(
        "--codes",
        nargs="+",
        default=config.WATCHLIST,
        metavar="CODE",
        help="标的代码列表（默认使用 config.WATCHLIST）",
    )
    args = parser.parse_args()
    run_update(args.codes)


if __name__ == "__main__":
    main()
