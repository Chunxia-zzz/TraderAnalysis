"""一次性脚本：补全新标的 K 线数据 + 为所有标的拉取 4H K 线。

- 新标的（DB 中无日线）：拉取近 3 个月日线 + 周线 + 4H
- 存量标的（DB 中已有日线）：只拉取近 3 个月 4H

用法:
    python scripts/backfill_klines.py [--dry-run] [--only-4h]
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
    """统一列名、格式化日期、计算指标。"""
    if df.empty:
        return df

    # 统一列名
    if "time_key" in df.columns:
        df = df.rename(columns={"time_key": "date"})

    # 日期格式化
    if ktype == "4h":
        # 4H 保留时间: "YYYY-MM-DD HH:MM:SS"
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        # 日线/周线只保留日期
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

    # 去重 + 排序
    df = df.drop_duplicates(subset=["date"], keep="last")
    df = df.sort_values("date").reset_index(drop=True)

    # 计算指标
    df = calc_indicators(df, indicator_config)
    return df


def run_backfill(dry_run: bool = False, only_4h: bool = False):
    from futu import OpenQuoteContext, KLType

    init_db()

    # 获取标的池所有代码
    import sqlite3
    conn = sqlite3.connect(config.DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT code FROM watchlist")
    codes = [r[0] for r in cur.fetchall()]
    conn.close()

    # 分类：新标的 vs 存量
    new_codes = []
    existing_codes = []
    for code in codes:
        if get_latest_date(code, "1d") is None:
            new_codes.append(code)
        else:
            existing_codes.append(code)

    logger.info(f"标的池: {len(codes)} 只 (存量: {len(existing_codes)}, 新标的: {len(new_codes)})")
    logger.info(f"日期范围: {THREE_MONTHS_AGO} ~ {TODAY}")

    if dry_run:
        logger.info("[DRY RUN] 不实际拉取")
        logger.info(f"  新标的需拉取: 日线+周线+4H × {len(new_codes)} 只")
        logger.info(f"  存量需拉取: 4H × {len(existing_codes)} 只")
        return

    quote_ctx = OpenQuoteContext(host=config.OPEND_HOST, port=config.OPEND_PORT)

    try:
        total = len(codes)
        success = 0
        failed = 0
        idx = 0

        # ── Step 1: 新标的拉取日线+周线+4H ──
        if not only_4h:
            for code in new_codes:
                idx += 1
                logger.info(f"[{idx}/{total}] 新标的 {code} — 拉取日线+周线+4H")

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

                    # 4H
                    df = fetch_history_kline(quote_ctx, code, KLType.K_240M, THREE_MONTHS_AGO, TODAY)
                    df = process_kline_df(df, "4h", config.FOUR_HOUR_INDICATOR_CONFIG)
                    n = batch_upsert(code, "4h", df) if not df.empty else 0
                    logger.info(f"  4H: {n} 根")
                    time.sleep(REQUEST_DELAY)

                    success += 1
                except Exception as e:
                    failed += 1
                    logger.error(f"  {code} 失败: {e}")
                    time.sleep(REQUEST_DELAY)

        # ── Step 2: 存量标的只拉取 4H ──
        for code in existing_codes:
            idx += 1
            logger.info(f"[{idx}/{total}] 存量 {code} — 拉取 4H")

            try:
                df = fetch_history_kline(quote_ctx, code, KLType.K_240M, THREE_MONTHS_AGO, TODAY)
                df = process_kline_df(df, "4h", config.FOUR_HOUR_INDICATOR_CONFIG)
                n = batch_upsert(code, "4h", df) if not df.empty else 0
                logger.info(f"  4H: {n} 根")
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
    only_4h = "--only-4h" in sys.argv
    run_backfill(dry_run=dry_run, only_4h=only_4h)
