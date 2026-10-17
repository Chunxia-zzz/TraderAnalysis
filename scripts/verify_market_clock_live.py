"""联网端到端验证 `market_clock` 的半截 K 线拦截（需 OpenD 在 11111 端口）。

验证方式：**不走 mock 的过滤函数，而是直接跑真实的 `daily_update._update_ktype()`**，
只把「当前时间」注入成假的盘中时刻，落库指向一个临时 DB 副本，
这样既能验证真实 Futu 返回的 K 线格式，又不会污染生产库。

跑法：
    .venv/Scripts/python.exe scripts/verify_market_clock_live.py
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
SRC_DB = ROOT / "data" / "indicators.db"

# 必须在 import config 之前设好，config.DB_PATH 在导入时就固定了
_TMP_DB = Path(tempfile.gettempdir()) / "verify_market_clock.db"
if SRC_DB.exists():
    shutil.copy2(SRC_DB, _TMP_DB)
os.environ["TA_DB_PATH"] = str(_TMP_DB)
sys.path.insert(0, str(ROOT / "src"))

from futu import KLType, OpenQuoteContext  # noqa: E402

from trader_analysis.futu_strategy import config, market_clock  # noqa: E402
from trader_analysis.futu_strategy.daily_update import _update_ktype  # noqa: E402
from trader_analysis.futu_strategy.providers import FutuLiveDataProvider  # noqa: E402

ET = ZoneInfo("America/New_York")
HKT = ZoneInfo("Asia/Hong_Kong")
FAKE_INTRADAY = datetime(2026, 10, 16, 12, 19, tzinfo=ET)  # 周五美东盘中（本次踩坑的真实时刻）

CODES = ["US.SPY", "US.AAPL", "HK.00700"]
BAR_DATE = "2026-10-16"     # 目标交易日
WEEK_MONDAY = "2026-10-12"  # 该周周线 date
BACKDATE = "2026-10-15"     # 把库回退到的「上一交易日」

ok = fail = 0


def check(cond: bool, label: str) -> None:
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✅ {label}")
    else:
        fail += 1
        print(f"  ❌ {label}")


def reset_db() -> None:
    """把目标交易日之后的数据删掉，模拟「只有上一交易日数据」的库。"""
    c = sqlite3.connect(str(_TMP_DB), timeout=30)
    c.execute("delete from kline_indicators where ktype='1d' and date>=?", (BAR_DATE,))
    c.execute("delete from kline_indicators where ktype='1w' and date>=?", (WEEK_MONDAY,))
    c.execute("delete from kline_indicators where ktype='4h' and date>=?", (BAR_DATE,))
    c.commit()
    c.close()


def rows(code: str, ktype: str) -> list[str]:
    c = sqlite3.connect(str(_TMP_DB), timeout=30)
    r = [x[0] for x in c.execute(
        "select date from kline_indicators where ktype=? and (code=? or code=?) and date>=? order by date",
        (ktype, code, code.replace("US.", ""), BAR_DATE if ktype != "1w" else WEEK_MONDAY),
    )]
    c.close()
    return r


def latest(code: str, ktype: str) -> str | None:
    c = sqlite3.connect(str(_TMP_DB), timeout=30)
    r = c.execute(
        "select max(date) from kline_indicators where ktype=? and (code=? or code=?)",
        (ktype, code, code.replace("US.", "")),
    ).fetchone()
    c.close()
    return r[0] if r else None


def patch_now(fake: datetime | None) -> None:
    """把 market_clock.now_in_market 的默认时间替换掉（None = 恢复真实时间）。"""
    if fake is None:
        market_clock.now_in_market = _ORIG_NOW
    else:
        market_clock.now_in_market = lambda code, now=None: fake.astimezone(market_clock.market_tz(code))


_ORIG_NOW = market_clock.now_in_market


def main() -> int:
    if not SRC_DB.exists():
        print("找不到 data/indicators.db")
        return 2

    ctx = OpenQuoteContext(host=config.OPEND_HOST, port=config.OPEND_PORT)
    provider = FutuLiveDataProvider()
    try:
        # ── 第 1 部分：真实 K 线格式核对（确认 date 语义与模块注释一致）────────────
        print("\n[1] 真实 K 线格式（date 语义）")
        seq = {}
        for code in CODES:
            for ktype, kl in (("1d", KLType.K_DAY), ("1w", KLType.K_WEEK), ("4h", KLType.K_240M)):
                df = provider.get_kline(ctx, code, kl_type=kl, count=12, timeframe=ktype)
                col = "date" if "date" in df.columns else ("timestamp" if "timestamp" in df.columns else "time_key")
                vals = [str(v) for v in df[col].tolist()]
                seq[(code, ktype)] = vals
                tail = vals[-3:]
                print(f"    {code:9s} {ktype:2s} n={len(vals):2d} 末尾={tail}")

        # 4H 的 date 应当是「结束时刻」：美股 13:30 / 16:00（半日市 13:00），港股 12:00 / 16:00
        us4h = [v[11:16] for v in seq[("US.SPY", "4h")]]
        check(all(t in ("13:00", "13:30", "16:00") for t in us4h),
              f"美股 4H 标签是结束时刻 13:30/16:00、半日市 13:00（实际 {sorted(set(us4h))}）")
        half_days = sorted({v[:10] for v in seq[("US.SPY", "4h")] if v[11:16] == "13:00"})
        print(f"       其中 13:00 的日期（应为半日市）= {half_days}")
        check(all(h in ("2025-11-28", "2025-12-24") for h in half_days),
              f"13:00 全部是已知半日市（感恩节次日/平安夜）：{half_days}")
        hk4h = [v[11:16] for v in seq[("HK.00700", "4h")]]
        check(all(t in ("12:00", "16:00") for t in hk4h), f"港股 4H 标签是结束时刻 12:00/16:00（实际 {sorted(set(hk4h))}）")
        # 周线 date 应是周一
        for code in CODES:
            wk = seq[(code, "1w")]
            check(all(datetime.strptime(v[:10], "%Y-%m-%d").weekday() == 0 for v in wk),
                  f"{code} 周线 date 全部是周一")

        # ── 第 2 部分：真实当前时间（周六，全部已收盘）不应误杀任何 K 线 ──────────
        print("\n[2] 当前真实时间 = 周六，filter 不应丢任何 K 线")
        now_real = datetime.now(ZoneInfo("UTC"))
        print(f"    当前 UTC={now_real:%Y-%m-%d %H:%M}  美东={now_real.astimezone(ET):%Y-%m-%d %H:%M %A}")
        for code in CODES:
            for ktype in ("1d", "1w", "4h"):
                vals = seq[(code, ktype)]
                dropped = [v for v in vals if not market_clock.is_bar_closed(ktype, v, code)]
                check(not dropped, f"{code} {ktype} 无丢弃（若丢弃：{dropped[:3]}）")

        # ── 第 3 部分：注入盘中时刻，真实 _update_ktype 必须拦住 ─────────────────
        # 关键：同一时刻对两个市场结论不同
        #   美东 10/16 12:19  →  美股盘中（周五未收盘）→ 必须全部拦住
        #   美东 10/16 12:19  =  香港 10/17 00:19（周六凌晨）→ 港股 10/16 早已收盘 → 必须放行
        print("\n[3] 注入盘中时刻 2026-10-16 12:19 ET（= 香港 10/17 00:19），跑真实 _update_ktype")
        reset_db()
        for code in CODES:
            assert latest(code, "1d") == BACKDATE, f"{code} 回退失败：{latest(code, '1d')}"

        patch_now(FAKE_INTRADAY)
        cfg_map = {"1d": (config.DAILY_INDICATOR_CONFIG, config.DAILY_KLINE_COUNT),
                   "1w": (config.WEEKLY_INDICATOR_CONFIG, config.WEEKLY_KLINE_COUNT),
                   "4h": (config.FOUR_HOUR_INDICATOR_CONFIG, config.INIT_4H_KLINE_COUNT)}
        stats: dict = {"count": 0, "kinds": set()}
        written = {}
        for code in CODES:
            for ktype, (icfg, cnt) in cfg_map.items():
                written[(code, ktype)] = _update_ktype(ctx, provider, code, ktype, icfg, cnt, stats)
        print(f"    写入行数 = {written}")
        print(f"    拦截统计 = count={stats['count']} kinds={sorted(stats['kinds'])}")

        check(callable(market_clock.allow_partial_bar) and not market_clock.allow_partial_bar(),
              "TA_ALLOW_PARTIAL_BAR 关闭（默认拦截）")
        # 美股：三个周期全部拦住
        for code in ("US.SPY", "US.AAPL"):
            check(latest(code, "1d") == BACKDATE, f"{code}（美股盘中）1d 被拦住，仍 {latest(code, '1d')}")
            check(all(written[(code, k)] == 0 for k in cfg_map), f"{code} 1d/1w/4h 写入数全为 0")
            got = rows(code, "4h")
            check(not any(v.startswith(BAR_DATE) for v in got), f"{code} 4h 无 {BAR_DATE} 的行（{'空' if not got else got[-2:]}）")
        # 港股：同一时刻已收盘，必须放行（时区分支生效的反证）
        check(written[("HK.00700", "1d")] >= 1, f"HK.00700（已收盘）1d 正常写入 {written[('HK.00700', '1d')]} 根")
        check(latest("HK.00700", "1d") == BAR_DATE, f"HK.00700 1d 最新 = {latest('HK.00700', '1d')}")
        check(stats["count"] > 0, f"确实拦到了 K 线（共 {stats['count']} 根）")

        # ── 第 4 部分：恢复真实时间，美股必须能正常写入 ──────────────────────────
        print("\n[4] 恢复真实时间，重跑同一批标的（美股应正常写入完整 K 线）")
        patch_now(None)
        written2 = {}
        stats2: dict = {"count": 0, "kinds": set()}
        for code in CODES:
            for ktype, (icfg, cnt) in cfg_map.items():
                written2[(code, ktype)] = _update_ktype(ctx, provider, code, ktype, icfg, cnt, stats2)
        print(f"    写入行数 = {written2}   拦截统计 = {stats2}")

        for code in ("US.SPY", "US.AAPL"):
            check(written2[(code, "1d")] >= 1, f"{code} 1d 正常写入 {written2[(code, '1d')]} 根")
            check(latest(code, "1d") == BAR_DATE, f"{code} 1d 最新 = {latest(code, '1d')}")
            got4 = [v for v in rows(code, "4h") if v.startswith(BAR_DATE)]
            check(len(got4) >= 1, f"{code} 4h 已写入 {BAR_DATE} 共 {len(got4)} 根：{[v[11:16] for v in got4]}")
        check(stats2["count"] == 0, f"收盘后不再拦截（count={stats2['count']}）")
        got4 = [v for v in rows("HK.00700", "4h") if v.startswith(BAR_DATE)]
        check(len(got4) >= 1, f"HK.00700 4h 保留 {BAR_DATE} 共 {len(got4)} 根：{[v[11:16] for v in got4]}")

        # ── 第 5 部分：TA_ALLOW_PARTIAL_BAR=1 开关应恢复旧行为 ───────────────────
        print("\n[5] 开关 TA_ALLOW_PARTIAL_BAR=1 时恢复旧行为（不拦截）")
        reset_db()
        os.environ["TA_ALLOW_PARTIAL_BAR"] = "1"
        patch_now(FAKE_INTRADAY)
        stats3: dict = {"count": 0, "kinds": set()}
        n3 = {}
        for code in CODES:
            n3[(code, "1d")] = _update_ktype(ctx, provider, code, "1d", config.DAILY_INDICATOR_CONFIG,
                                            config.DAILY_KLINE_COUNT, stats3)
        os.environ.pop("TA_ALLOW_PARTIAL_BAR", None)
        patch_now(None)
        print(f"    写入行数 = {n3}  拦截统计 = {stats3}")
        check(all(v >= 1 for v in n3.values()), "开关打开后照旧写入（按旧行为）")
        check(stats3["count"] == 0, "开关打开时不做拦截")
    finally:
        ctx.close()
        try:
            _TMP_DB.unlink(missing_ok=True)
        except Exception:
            pass

    print(f"\n===== 结果：{ok} 通过 / {fail} 失败 =====")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
