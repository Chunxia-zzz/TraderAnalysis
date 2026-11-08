"""一次性脚本：补全新标的的日线与周线 K 线数据。

- 只处理 DB 中还没有日线的新标的（存量标的走日常 `trader-analysis update`）
- 4H 周期已于 2026-11-08 下线（见 `specs/002-remove-4h-cycle`），本脚本不再处理

用法:
    python scripts/backfill_klines.py [--dry-run]
"""

import sys
import os
import time
import logging
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from trader_analysis.futu_strategy import config
from trader_analysis.futu_strategy.indicators import calc_indicators
from trader_analysis.futu_strategy.storage import (
    batch_upsert, get_latest_date, init_db,
)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# 3 个月前的日期
THREE_MONTHS_AGO = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
TODAY = datetime.now().strftime("%Y-%m-%d")

# API 限频间隔
REQUEST_DELAY = 3.0


def fetch_history_kline(quote_ctx, code: str, kl_type, start: str, end: str) -> pd.DataFrame:
    """拉取历史 K 线，自动翻页。"""
    from futu import RET_OK

    all_data = []
    page_req_key = None
    max_pages = 5

    for _ in range(max_pages):
        ret, data, page_req_key = quote_ctx.request_history_kline(
            code, ktype=kl_type, start=start, end=end,
            max_count=200, page_req_key=page_req_key,
        )
        if ret != RET_OK:
            logger.error(f"  {code} 拉取失败: {data}")
            break
        all_data.append(data)
        if page_req_key is None:
            break
        time.sleep(0.5)

    if not all_data:
        return pd.DataFrame()

    df = pd.concat(all_data, ignore_index=True)
    return df


def process_kline_df(df: pd.DataFrame, ktype: str, indicator_config: dict) -> pd.DataFrame:
    """统一列名、格式化日期、计算指标。

    `ktype` 只接受 `1d` / `1w`，两者都只保留日期部分。
    """
    if df.empty:
        return df

    # 统一列名
    if "time_key" in df.columns:
        df = df.rename(columns={"time_key": "date"})

    # 日线/周线只保留日期
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

    # 去重 + 排序
    df = df.drop_duplicates(subset=["date"], keep="last")
    df = df.sort_values("date").reset_index(drop=True)

    # 计算指标
    df = calc_indicators(df, indicator_config)
    return df


def run_backfill(dry_run: bool = False):
    from futu import OpenQuoteContext, KLType

    init_db()

    # 获取标的池所有代码
    import sqlite3
    conn = sqlite3.connect(config.DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT code FROM watchlist")
    codes = [r[0] for r in cur.fetchall()]
    conn.close()

    # 只有「DB 中无日线」的标的需要补历史
    new_codes = [code for code in codes if get_latest_date(code, "1d") is None]
    skipped = len(codes) - len(new_codes)

    logger.info(f"标的池: {len(codes)} 只 (已有日线跳过: {skipped}, 待补: {len(new_codes)})")
    logger.info(f"日期范围: {THREE_MONTHS_AGO} ~ {TODAY}")

    if dry_run:
        logger.info("[DRY RUN] 不实际拉取")
        logger.info(f"  新标的需拉取: 日线+周线 × {len(new_codes)} 只")
        return

    if not new_codes:
        logger.info("所有标的均已有日线数据，无需补数")
        return

    quote_ctx = OpenQuoteContext(host=config.OPEND_HOST, port=config.OPEND_PORT)

    try:
        total = len(new_codes)
        success = 0
        failed = 0

        for idx, code in enumerate(new_codes, 1):
            logger.info(f"[{idx}/{total}] 新标的 {code} — 拉取日线+周线")

            try:
                # 日线
                df = fetch_history_kline(quote_ctx, code, KLType.K_DAY, THREE_MONTHS_AGO, TODAY)
                df = process_kline_df(df, "1d", config.DAILY_INDICATOR_CONFIG)
                n = batch_upsert(code, "1d", df) if not df.empty else 0
                logger.info(f"  日线: {n} 根")
                time.sleep(REQUEST_DELAY)

                # 周线
                df = fetch_history_kline(quote_ctx, code, KLType.K_WEEK, THREE_MONTHS_AGO, TODAY)
                df = process_kline_df(df, "1w", config.WEEKLY_INDICATOR_CONFIG)
                n = batch_upsert(code, "1w", df) if not df.empty else 0
                logger.info(f"  周线: {n} 根")
                time.sleep(REQUEST_DELAY)

                success += 1
            except Exception as e:
                failed += 1
                logger.error(f"  {code} 失败: {e}")
                time.sleep(REQUEST_DELAY)

        logger.info(f"\n{'='*60}")
        logger.info(f"完成! 成功: {success}, 失败: {failed}")

    finally:
        quote_ctx.close()
        logger.info("连接已关闭")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run_backfill(dry_run=dry_run)
