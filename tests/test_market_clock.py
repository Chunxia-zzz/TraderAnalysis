"""market_clock 的 K 线「是否已收盘」判定测试。

覆盖 2026-10-17 真实踩过的场景：北京时间盘后跑 update 会把当天进行中的
那根 K 线写进库，而增量落库是 `date > last_date`（严格大于）→ 永不覆盖。
这些用例把判定规则钉死，防止以后「优化」时又放半截 K 线进库。
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from trader_analysis.futu_strategy.market_clock import (
    filter_closed_bars,
    is_bar_closed,
    market_tz,
)

ET = ZoneInfo("America/New_York")
HKT = ZoneInfo("Asia/Hong_Kong")


# ── 时区选择 ────────────────────────────────────────────────────────────────


def test_market_tz_us_and_hk():
    assert str(market_tz("US.SPY")) == "America/New_York"
    assert str(market_tz("HK.00700")) == "Asia/Hong_Kong"
    # 无前缀一律按美股
    assert str(market_tz("AAPL")) == "America/New_York"


# ── 日线 ────────────────────────────────────────────────────────────────────


def test_daily_intraday_bar_dropped():
    """美东 12:19 盘中（= 北京 00:19）→ 当天的日线必须丢掉。"""
    now = datetime(2026, 10, 16, 12, 19, tzinfo=ET)
    assert is_bar_closed("1d", "2026-10-16", "US.SPY", now) is False
    assert is_bar_closed("1d", "2026-10-15", "US.SPY", now) is True


def test_daily_bar_kept_after_close():
    now = datetime(2026, 10, 16, 16, 1, tzinfo=ET)
    assert is_bar_closed("1d", "2026-10-16", "US.SPY", now) is True


def test_daily_bar_at_exact_close_boundary():
    now = datetime(2026, 10, 16, 16, 0, tzinfo=ET)
    assert is_bar_closed("1d", "2026-10-16", "US.SPY", now) is True
    now_before = datetime(2026, 10, 16, 15, 59, 59, tzinfo=ET)
    assert is_bar_closed("1d", "2026-10-16", "US.SPY", now_before) is False


def test_daily_bar_kept_on_later_day():
    """周六回看周五 → 周五那根早已定稿。"""
    now = datetime(2026, 10, 17, 11, 28, tzinfo=ET)
    assert is_bar_closed("1d", "2026-10-16", "US.SPY", now) is True


def test_daily_hk_uses_hong_kong_clock():
    """港股用香港时间判定：北京/香港 15:00 收盘前不算定稿。"""
    now = datetime(2026, 10, 16, 15, 0, tzinfo=HKT)
    assert is_bar_closed("1d", "2026-10-16", "HK.00700", now) is False
    now2 = datetime(2026, 10, 16, 16, 5, tzinfo=HKT)
    assert is_bar_closed("1d", "2026-10-16", "HK.00700", now2) is True


# ── 周线（date 记的是该周周一） ─────────────────────────────────────────────


def test_weekly_current_week_dropped_before_friday_close():
    """10/12 周一那根周线：周五收盘前都不算定稿。"""
    now = datetime(2026, 10, 16, 12, 19, tzinfo=ET)  # 周五盘中
    assert is_bar_closed("1w", "2026-10-12", "US.SPY", now) is False


def test_weekly_current_week_kept_after_friday_close():
    now = datetime(2026, 10, 16, 16, 1, tzinfo=ET)
    assert is_bar_closed("1w", "2026-10-12", "US.SPY", now) is True


def test_weekly_past_week_always_kept():
    now = datetime(2026, 10, 14, 10, 0, tzinfo=ET)
    assert is_bar_closed("1w", "2026-10-05", "US.SPY", now) is True


def test_weekly_date_not_monday_still_normalized():
    """防御性：即便 Futu 给的周线 date 不是周一，也要按「该周周五 16:00」判定。

    实测 52 周全为周一，但这里不依赖那个隐含前提。
    """
    now = datetime(2026, 10, 14, 10, 0, tzinfo=ET)  # 周三
    # 传入周三 10/14，归一化后仍是本周 → 本周五未收盘
    assert is_bar_closed("1w", "2026-10-14", "US.SPY", now) is False
    # 传入周五 10/09（上一周的周五）→ 归一化到 10/05 那周，早已收盘
    assert is_bar_closed("1w", "2026-10-09", "US.SPY", now) is True
    # 传入周日 10/18 → 归一化到 10/12 那周 → 本周五 10/16 16:00 还没到（now 是 10/14 周三）
    assert is_bar_closed("1w", "2026-10-18", "US.SPY", now) is False
    # 传入上周日 10/11 → 归一化到 10/05 那周 → 该周周五 10/09 16:00 已过
    assert is_bar_closed("1w", "2026-10-11", "US.SPY", now) is True


# ── 4H（date 是 K 线结束时刻） ─────────────────────────────────────────────


def test_4h_bar_dropped_while_running():
    """美东 12:19，13:30 那根还没走完 → 丢掉；前一天的保留。"""
    now = datetime(2026, 10, 16, 12, 19, tzinfo=ET)
    assert is_bar_closed("4h", "2026-10-16 13:30:00", "US.SPY", now) is False
    assert is_bar_closed("4h", "2026-10-16 16:00:00", "US.SPY", now) is False
    assert is_bar_closed("4h", "2026-10-15 16:00:00", "US.SPY", now) is True


def test_4h_bar_kept_when_finished():
    now = datetime(2026, 10, 16, 13, 31, tzinfo=ET)
    assert is_bar_closed("4h", "2026-10-16 13:30:00", "US.SPY", now) is True
    assert is_bar_closed("4h", "2026-10-16 16:00:00", "US.SPY", now) is False


def test_4h_hk_bars():
    now = datetime(2026, 10, 16, 12, 30, tzinfo=HKT)
    assert is_bar_closed("4h", "2026-10-16 12:00:00", "HK.00700", now) is True
    assert is_bar_closed("4h", "2026-10-16 16:00:00", "HK.00700", now) is False


def test_4h_half_day_close_1300():
    """半日市（2025-11-28 感恩节次日 / 2025-12-24 平安夜）4H 标签是 13:00，当天只有 1 根。

    联网实测：500 根 SPY 4H 里恰好这 2 天是 13:00。
    13:00 之后就该入库，不能死等 16:00。
    """
    assert is_bar_closed("4h", "2025-11-28 13:00:00", "US.SPY",
                         datetime(2025, 11, 28, 12, 59, tzinfo=ET)) is False
    assert is_bar_closed("4h", "2025-11-28 13:00:00", "US.SPY",
                         datetime(2025, 11, 28, 13, 1, tzinfo=ET)) is True
    # 同一天日线仍按 16:00 判定（半日市 1d 会晚 3 小时入库，方向安全）
    assert is_bar_closed("1d", "2025-11-28", "US.SPY",
                         datetime(2025, 11, 28, 13, 1, tzinfo=ET)) is False


# ── 跨市场：同一时刻两侧结论相反 ────────────────────────────────────────────


def test_same_instant_us_intraday_hk_closed():
    """美东周五 12:19 = 香港周六 00:19：美股要拦，港股必须放行。

    这是时区分支是否真正生效的关键反证（2026-10-17 联网验证也覆盖了这条）。
    """
    now = datetime(2026, 10, 16, 12, 19, tzinfo=ET)
    assert is_bar_closed("1d", "2026-10-16", "US.SPY", now) is False
    assert is_bar_closed("1d", "2026-10-16", "HK.00700", now) is True
    assert is_bar_closed("4h", "2026-10-16 16:00:00", "US.SPY", now) is False
    assert is_bar_closed("4h", "2026-10-16 16:00:00", "HK.00700", now) is True
    assert is_bar_closed("1w", "2026-10-12", "US.SPY", now) is False
    assert is_bar_closed("1w", "2026-10-12", "HK.00700", now) is True


# ── 兜底与 DataFrame 过滤 ──────────────────────────────────────────────────


def test_unknown_ktype_always_kept():
    assert is_bar_closed("1m", "2026-10-16", "US.SPY", datetime.now(ET)) is True


def test_unparsable_value_kept():
    """解析失败宁可放行，也不要静默丢掉整批数据。"""
    now = datetime(2026, 10, 16, 12, 0, tzinfo=ET)
    assert is_bar_closed("1d", "", "US.SPY", now) is True
    assert is_bar_closed("1d", "not-a-date", "US.SPY", now) is True


def test_filter_closed_bars_drops_partial_rows():
    df = pd.DataFrame(
        {
            "date": ["2026-10-14", "2026-10-15", "2026-10-16"],
            "close": [1.0, 2.0, 3.0],
        }
    )
    now = datetime(2026, 10, 16, 12, 19, tzinfo=ET)
    out = filter_closed_bars(df, "1d", "US.SPY", now)
    assert len(out) == 2
    assert out["date"].iloc[-1] == "2026-10-15"
    # 原 DataFrame 不被修改
    assert len(df) == 3


def test_filter_closed_bars_keeps_all_after_close():
    df = pd.DataFrame({"date": ["2026-10-15", "2026-10-16"], "close": [1.0, 2.0]})
    now = datetime(2026, 10, 16, 16, 30, tzinfo=ET)
    assert len(filter_closed_bars(df, "1d", "US.SPY", now)) == 2


def test_allow_partial_env_overrides(monkeypatch):
    """TA_ALLOW_PARTIAL_BAR=1 时恢复旧行为（调试/补偿用）。"""
    df = pd.DataFrame({"date": ["2026-10-16"], "close": [1.0]})
    now = datetime(2026, 10, 16, 12, 19, tzinfo=ET)
    monkeypatch.setenv("TA_ALLOW_PARTIAL_BAR", "1")
    assert len(filter_closed_bars(df, "1d", "US.SPY", now)) == 1
    monkeypatch.setenv("TA_ALLOW_PARTIAL_BAR", "0")
    assert len(filter_closed_bars(df, "1d", "US.SPY", now)) == 0
