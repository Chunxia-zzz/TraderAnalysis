"""SQLite 存储层 CRUD 测试（使用临时数据库）。"""

import os
import tempfile

import pandas as pd
import pytest

from trader_analysis.futu_strategy import storage


@pytest.fixture(autouse=True)
def _tmp_db(monkeypatch, tmp_path):
    """将 DB_PATH 指向临时文件，避免污染真实数据库。"""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("trader_analysis.futu_strategy.config.DB_PATH", db_path)
    storage.init_db()
    yield


def _make_df(dates: list[str], close_values: list[float]) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame({
        "timestamp": dates,
        "open": close_values,
        "high": [v + 1 for v in close_values],
        "low": [v - 1 for v in close_values],
        "close": close_values,
        "volume": [1000] * n,
        "turnover": [10000] * n,
        "ma5": [None] * n,
        "ma10": [None] * n,
        "ma20": [None] * n,
        "ma60": [None] * n,
        "ma120": [None] * n,
        "ma200": [None] * n,
        "ma250": [None] * n,
        "rsi6": [50.0] * n,
        "rsi12": [50.0] * n,
        "rsi24": [50.0] * n,
        "dif": [0.0] * n,
        "dea": [0.0] * n,
        "macd": [0.0] * n,
        "boll_upper": [None] * n,
        "boll_mid": [None] * n,
        "boll_lower": [None] * n,
        "vol_ma20": [None] * n,
    })


def test_batch_upsert_and_query_recent():
    df = _make_df(["2026-04-01", "2026-04-02", "2026-04-03"], [100.0, 101.0, 102.0])
    count = storage.batch_upsert("US.TEST", "1d", df)
    assert count == 3

    result = storage.query_recent("US.TEST", "1d", limit=10)
    assert len(result) == 3
    assert result.iloc[-1]["close"] == 102.0


def test_list_codes():
    df = _make_df(["2026-04-01"], [100.0])
    storage.batch_upsert("US.AAA", "1d", df)
    storage.batch_upsert("US.BBB", "1d", df)

    codes = storage.list_codes()
    assert "US.AAA" in codes
    assert "US.BBB" in codes


def test_get_latest_date():
    df = _make_df(["2026-04-01", "2026-04-02"], [100.0, 101.0])
    storage.batch_upsert("US.TEST", "1d", df)

    assert storage.get_latest_date("US.TEST", "1d") == "2026-04-02"
    assert storage.get_latest_date("US.NONE", "1d") is None


def test_query_range():
    df = _make_df(["2026-04-01", "2026-04-02", "2026-04-03"], [100.0, 101.0, 102.0])
    storage.batch_upsert("US.TEST", "1d", df)

    rows = storage.query_range("US.TEST", "1d", days=2)
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-04-02"  # 升序，最近 2 根
    assert rows[1]["date"] == "2026-04-03"


def test_query_latest():
    df = _make_df(["2026-04-01", "2026-04-02"], [100.0, 101.0])
    storage.batch_upsert("US.TEST", "1d", df)

    latest = storage.query_latest("US.TEST", "1d")
    assert latest["date"] == "2026-04-02"
    assert latest["close"] == 101.0


def test_query_latest_empty():
    result = storage.query_latest("US.NONE", "1d")
    assert result == {}


def test_upsert_and_query_score():
    score_result = {
        "total_score": 85,
        "signal": "BUY",
        "breakdown": {"c1": {"score": 22, "triggered": True}},
    }
    storage.upsert_score("US.TEST", "2026-04-01", score_result)

    result = storage.query_latest_score("US.TEST")
    assert result["total_score"] == 85
    assert result["signal"] == "BUY"
    assert result["breakdown"]["c1"]["triggered"] is True


def test_query_latest_score_empty():
    result = storage.query_latest_score("US.NONE")
    assert result == {}
