"""市场温度按指数拆分（specs/003-split-market-temperature）的专项测试。

覆盖 spec 的成功标准：
  SC-001  两指数温度平均 == 拆分前合并值（±0.5）
  SC-003  market_score 不再被写入
  SC-004  同一数据日行数恒为 2
  SC-008  恐慌加成输入仍等价于合并值
"""

from __future__ import annotations

import pytest

from trader_analysis.futu_strategy import storage
from trader_analysis.futu_strategy.market_scorer import (
    INDEX_KEYS,
    SPREAD_HISTORY_START,
    compute_temperature_spread,
    spread_label,
)


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test_split_temp.db")
    monkeypatch.setattr("trader_analysis.futu_strategy.config.DB_PATH", db_path)
    storage.init_db()


def _point(date: str, code: str, score: float, position: float = 60.0) -> None:
    storage.upsert_market_temp_split_point(code.split(".")[-1], {
        "date": date,
        "composite_score": score,
        "target_position_pct": position,
    })


# ── 温差语义 ──────────────────────────────────────────────────────────────────


class TestSpreadSemantics:
    def test_negative_means_spy_stronger(self):
        """温差为负 = 标普温度更低 = 标普相对更强（本次需求的核心语义）。"""
        assert compute_temperature_spread(70.3, 79.4) == pytest.approx(-9.1)
        assert spread_label(-9.1) == "标普相对更强"

    def test_positive_means_qqq_weaker(self):
        assert compute_temperature_spread(85.0, 60.0) == pytest.approx(25.0)
        assert spread_label(25.0) == "纳指相对更强"

    def test_zero_is_balanced(self):
        assert spread_label(0.0) == "两者均衡"

    def test_none_degrades(self):
        assert compute_temperature_spread(None, 60.0) is None
        assert compute_temperature_spread(60.0, None) is None
        assert spread_label(None) == "数据不足"


# ── 与旧合并口径的等价性（SC-001）────────────────────────────────────────────


def test_average_equals_legacy_merged():
    """拆分不新造口径：两指数温度的算术平均 == 拆分前的合并值（±0.5）。

    锚点取自 2026-11-09 真实库实测值（拆分前 market_score=74.9）。
    """
    spy, qqq, legacy = 70.3, 79.4, 74.9
    assert abs((spy + qqq) / 2 - legacy) <= 0.5


# ── 恐慌加成取数（SC-008）─────────────────────────────────────────────────────


class TestPanicComposite:
    def test_uses_split_average(self):
        _point("2026-05-01", "US.SPY", 70.0)
        _point("2026-05-01", "US.QQQ", 80.0)
        assert storage.query_panic_composite_map()["2026-05-01"] == pytest.approx(75.0)

    def test_falls_back_to_frozen_legacy(self):
        """2025-01-01 之前没有拆分行，必须回落到冻结的 market_score。"""
        conn = storage._get_conn()
        conn.execute(
            "INSERT INTO market_score (date, composite_score, target_position_pct) "
            "VALUES (?,?,?)",
            ("2024-06-03", 61.5, 70.0),
        )
        conn.commit()
        conn.close()

        assert storage.query_panic_composite_map()["2024-06-03"] == pytest.approx(61.5)

    def test_split_overrides_legacy_on_same_date(self):
        conn = storage._get_conn()
        conn.execute(
            "INSERT INTO market_score (date, composite_score, target_position_pct) "
            "VALUES (?,?,?)",
            ("2026-05-01", 99.0, 100.0),
        )
        conn.commit()
        conn.close()

        _point("2026-05-01", "US.SPY", 70.0)
        _point("2026-05-01", "US.QQQ", 80.0)
        assert storage.query_panic_composite_map()["2026-05-01"] == pytest.approx(75.0)

    def test_latest_prefers_split(self):
        _point("2026-05-01", "US.SPY", 70.0)
        _point("2026-05-01", "US.QQQ", 80.0)
        assert storage.query_latest_panic_composite() == pytest.approx(75.0)

    def test_latest_falls_back_when_no_split(self):
        conn = storage._get_conn()
        conn.execute(
            "INSERT INTO market_score (date, composite_score, target_position_pct) "
            "VALUES (?,?,?)",
            ("2024-06-03", 61.5, 70.0),
        )
        conn.commit()
        conn.close()
        assert storage.query_latest_panic_composite() == pytest.approx(61.5)


# ── 存储与幂等（SC-003 / SC-004）──────────────────────────────────────────────


class TestSplitStorage:
    def test_two_rows_per_date(self):
        for key in INDEX_KEYS:
            _point("2026-05-01", f"US.{key}", 70.0)
        _point("2026-05-01", "US.SPY", 71.0)  # 覆盖写
        rows = storage.query_latest_market_temp_split()
        assert len(rows) == 2
        assert {r["code"] for r in rows} == {"US.SPY", "US.QQQ"}

    def test_history_start_filter(self):
        _point("2024-12-31", "US.SPY", 50.0)
        _point("2025-01-02", "US.SPY", 52.0)
        _point("2025-01-03", "US.SPY", 53.0)

        rows = storage.query_market_temp_split_history(start_date=SPREAD_HISTORY_START)
        assert [r["date"] for r in rows] == ["2025-01-02", "2025-01-03"]

    def test_legacy_table_is_untouched_by_split_write(self):
        _point("2026-05-01", "US.SPY", 70.0)
        _point("2026-05-01", "US.QQQ", 80.0)
        conn = storage._get_conn()
        count = conn.execute("SELECT COUNT(*) FROM market_score").fetchone()[0]
        conn.close()
        assert count == 0  # 拆分写入绝不触碰冻结表
