"""全量重拉指定标的的 K 线（前复权 QFQ），修复拆股导致的未复权断层。

背景
----
`providers.py` 请求 K 线时确实传了 `autype=AuType.QFQ`，但 `run_update()`
（`daily_update.py:99`）是**增量拉取**。QFQ 前复权的基准是「最新价」——
每次除权后**全部历史都需重算**，而增量只追加新数据，
于是拆股前的价格停留在**旧复权基准**上，K 线里留下假断层。

典型案例：US.APH 2026-09-01 做 2:1 拆股，
日线出现 158.55 → 81.59（−48.5%）的假暴跌，导致 dd60 从真实约 +1.3%
变成 −49.3%，并污染周线 RSI（压到 18~25 的假超卖）。

修复方式：丢掉该标的的旧 K 线，用 QFQ 以最新基准全量重拉并重算指标。

用法
----
    # 重拉指定标的（日线 1000 根 / 周线 300 根 / 4H 1000 根）
    python scripts/refetch_klines.py US.APH HK.07709 US.KORU US.SOXL US.GDXU

    # 只看会做什么，不落库
    python scripts/refetch_klines.py --dry-run US.APH

    # 只重拉某几种周期
    python scripts/refetch_klines.py --ktypes 1d,1w US.APH

注意：重拉会**删除**该标的对应周期的旧行后再插入，请先确认已备份 DB。
"""

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trader_analysis.futu_strategy import config  # noqa: E402
from trader_analysis.futu_strategy.indicators import calc_indicators  # noqa: E402
from trader_analysis.futu_strategy.market_clock import filter_closed_bars  # noqa: E402
from trader_analysis.futu_strategy.storage import batch_upsert, init_db  # noqa: E402

# (ktype, Futu KLType 名称, 指标配置, 拉取根数)
KTYPE_SPECS = [
    ("1d", "K_DAY", lambda: config.DAILY_INDICATOR_CONFIG, 1000),
    ("1w", "K_WEEK", lambda: config.WEEKLY_INDICATOR_CONFIG, 300),
    ("4h", "K_240M", lambda: config.FOUR_HOUR_INDICATOR_CONFIG, 1000),
]

REQUEST_DELAY = 1.0
PAGE_DELAY = 1.0


def snapshot(code: str, ktype: str) -> dict:
    """记录重拉前的关键状态，用于前后对比。"""
    conn = sqlite3.connect(config.DB_PATH)
    try:
        rows = conn.execute(
            "SELECT date, close FROM kline_indicators "
            "WHERE code = ? AND ktype = ? ORDER BY date",
            (code, ktype),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return {"n": 0}
    win = rows[-60:] if ktype == "1d" else rows
    last = win[-1][1]
    mx = max(win, key=lambda x: x[1])
    return {
        "n": len(rows),
        "first": rows[0][0],
        "last": rows[-1][0],
        "close": last,
        "max_close": mx[1],
        "max_date": mx[0],
        "dd": round((last - mx[1]) / mx[1] * 100, 1) if mx[1] else None,
    }


def fetch_full(quote_ctx, code: str, kl_type, max_count: int) -> pd.DataFrame:
    """按 QFQ 全量拉取最近 max_count 根 K 线（自动翻页，忽略更早的分页）。"""
    from futu import RET_OK, AuType

    frames = []
    page_key = None
    for _ in range(6):
        ret, df, page_key = quote_ctx.request_history_kline(
            code,
            ktype=kl_type,
            autype=AuType.QFQ,  # 显式声明前复权，与增量更新保持一致
            max_count=1000,  # API 单次上限
            page_req_key=page_key,
        )
        if ret != RET_OK:
            raise RuntimeError(f"{code} 拉取失败: {df}")
        if df is None or df.empty:
            break
        frames.append(df)
        got = sum(len(f) for f in frames)
        if page_key is None or got >= max_count:
            break
        time.sleep(PAGE_DELAY)

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["time_key"], keep="last")
    return out.tail(max_count).reset_index(drop=True)


def process_kline_df(
    df: pd.DataFrame, ktype: str, indicator_config: dict, code: str = ""
) -> pd.DataFrame:
    """统一列名、格式化日期、丢弃未收盘 K 线、计算指标（与 backfill_klines.py 保持一致）。"""
    if df.empty:
        return df
    if "time_key" in df.columns:
        df = df.rename(columns={"time_key": "date"})
    if ktype == "4h":
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.drop_duplicates(subset=["date"], keep="last")
    df = df.sort_values("date").reset_index(drop=True)
    # 重拉会先 wipe 再写全量，若在盘中执行会把当天半截 K 线一起写回 → 这里同样拦掉
    df = filter_closed_bars(df, ktype, code)
    return calc_indicators(df, indicator_config)


def wipe(code: str, ktype: str) -> int:
    conn = sqlite3.connect(config.DB_PATH)
    try:
        cur = conn.execute(
            "DELETE FROM kline_indicators WHERE code = ? AND ktype = ?", (code, ktype)
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="全量重拉指定标的 K 线（QFQ 修复拆股断层）")
    ap.add_argument("codes", nargs="+", help="标的代码，如 US.APH HK.07709")
    ap.add_argument("--dry-run", action="store_true", help="不落库，仅预览")
    ap.add_argument(
        "--ktypes", default="1d,1w,4h", help="要重拉的周期，逗号分隔（默认 1d,1w,4h）"
    )
    args = ap.parse_args()

    wanted = [k.strip() for k in args.ktypes.split(",") if k.strip()]
    specs = [s for s in KTYPE_SPECS if s[0] in wanted]
    if not specs:
        print(f"无效的 --ktypes: {args.ktypes}")
        sys.exit(1)

    init_db()

    from futu import OpenQuoteContext, KLType

    print(f"标的: {args.codes}")
    print(f"周期: {[s[0] for s in specs]}")
    print(f"模式: {'DRY RUN（不落库）' if args.dry_run else '实际写入'}")
    print("=" * 78)

    quote_ctx = OpenQuoteContext(host=config.OPEND_HOST, port=config.OPEND_PORT)
    total_ok = 0
    try:
        for code in args.codes:
            print(f"\n### {code}")
            for ktype, kl_name, cfg_getter, max_count in specs:
                before = snapshot(code, ktype)
                try:
                    raw = fetch_full(quote_ctx, code, getattr(KLType, kl_name), max_count)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{ktype}] ✗ 拉取失败: {exc}")
                    time.sleep(REQUEST_DELAY)
                    continue

                if raw.empty:
                    print(f"  [{ktype}] ✗ 返回空数据，跳过（保留原数据）")
                    time.sleep(REQUEST_DELAY)
                    continue

                df = process_kline_df(raw.copy(), ktype, cfg_getter(), code)

                if args.dry_run:
                    print(
                        f"  [{ktype}] DRY: 拉取 {len(df)} 根  "
                        f"({df['date'].iloc[0]} ~ {df['date'].iloc[-1]})  "
                        f"原 {before.get('n', 0)} 根"
                    )
                    time.sleep(REQUEST_DELAY)
                    continue

                removed = wipe(code, ktype)
                written = batch_upsert(code, ktype, df)
                after = snapshot(code, ktype)
                total_ok += 1

                msg = (
                    f"  [{ktype}] ✓ 删除 {removed} 行 → 写入 {written} 行  "
                    f"({df['date'].iloc[0]} ~ {df['date'].iloc[-1]})"
                )
                if ktype == "1d" and before.get("dd") is not None:
                    msg += (
                        f"\n         dd60: {before['dd']:+.1f}% → {after.get('dd'):+.1f}%"
                        f"   现价: {before.get('close')} → {after.get('close')}"
                    )
                print(msg)
                time.sleep(REQUEST_DELAY)
    finally:
        quote_ctx.close()

    print("\n" + "=" * 78)
    print(f"完成，共 {total_ok} 个 (标的 × 周期) 组合{'（DRY RUN 未写入）' if args.dry_run else ' 已写入'}")
    if not args.dry_run:
        print("下一步：重跑评分 `python -m trader_analysis score --backfill 5`")


if __name__ == "__main__":
    main()
