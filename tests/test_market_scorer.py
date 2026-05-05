"""市场温度评分模块单元测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trader_analysis.futu_strategy import storage
from trader_analysis.futu_strategy.market_scorer import (
    NEUTRAL_SCORE,
    _calc_pct_b,
    _clamp,
    _map_status,
    _percentile_rank,
    _score_daily_tech,
    _score_price_position,
    _score_weekly_tech,
    calculate_market_temperature,
)


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch, tmp_path):
    """所有测试使用临时数据库，绝不触碰本地 indicators.db。"""
    db_path = str(tmp_path / "test_market_scorer.db")
    monkeypatch.setattr("trader_analysis.futu_strategy.config.DB_PATH", db_path)
    storage.init_db()
    yield


# ── 辅助：生成合成 K 线 DataFrame ─────────────────────────────────────────────


def _make_daily_df(
    n: int = 260, base_price: float = 500.0, seed: int = 42, *, for_storage: bool = False
) -> pd.DataFrame:
    """生成 n 行合成日线数据，含所有存储列。

    for_storage=True 时使用 "timestamp" 列名（适配 batch_upsert）;
    默认使用 "date"（适配 query_recent 返回格式，直接传给评分函数）。
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    closes = base_price + np.cumsum(rng.normal(0, 2, n))
    closes = np.maximum(closes, 50)  # 防止负值

    date_col = "timestamp" if for_storage else "date"
    df = pd.DataFrame({
        date_col: [d.strftime("%Y-%m-%d") for d in dates],
        "open": closes - rng.uniform(0, 2, n),
        "high": closes + rng.uniform(0, 5, n),
        "low": closes - rng.uniform(0, 5, n),
        "close": closes,
        "volume": rng.uniform(1e6, 5e6, n),
        "turnover": rng.uniform(1e8, 5e8, n),
    })

    # 模拟存储的指标列
    df["rsi6"] = 30 + rng.uniform(0, 40, n)  # RSI 30~70
    df["rsi12"] = 35 + rng.uniform(0, 30, n)
    df["rsi24"] = 40 + rng.uniform(0, 20, n)
    df["dif"] = rng.normal(0, 3, n)
    df["dea"] = rng.normal(0, 2, n)
    df["macd"] = (df["dif"] - df["dea"]) * 2
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["ma120"] = df["close"].rolling(120).mean()
    df["ma200"] = df["close"].rolling(200).mean()
    df["ma250"] = df["close"].rolling(250).mean()
    std20 = df["close"].rolling(20).std()
    df["boll_mid"] = df["ma20"]
    df["boll_upper"] = df["ma20"] + 2 * std20
    df["boll_lower"] = df["ma20"] - 2 * std20
    df["vol_ma20"] = df["volume"].rolling(20).mean()

    return df


def _make_weekly_df(
    n: int = 60, base_price: float = 500.0, seed: int = 43, *, for_storage: bool = False
) -> pd.DataFrame:
    """生成 n 行合成周线数据。"""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="W")
    closes = base_price + np.cumsum(rng.normal(0, 5, n))
    closes = np.maximum(closes, 50)

    date_col = "timestamp" if for_storage else "date"
    df = pd.DataFrame({
        date_col: [d.strftime("%Y-%m-%d") for d in dates],
        "open": closes - rng.uniform(0, 3, n),
        "high": closes + rng.uniform(0, 8, n),
        "low": closes - rng.uniform(0, 8, n),
        "close": closes,
        "volume": rng.uniform(5e6, 2e7, n),
        "rsi6": 35 + rng.uniform(0, 30, n),
        "rsi12": 40 + rng.uniform(0, 25, n),
        "rsi24": 42 + rng.uniform(0, 20, n),
        "dif": rng.normal(0, 5, n),
        "dea": rng.normal(0, 4, n),
        "macd": rng.normal(0, 3, n),
    })
    return df


# ── 辅助函数测试 ──────────────────────────────────────────────────────────────


class TestClamp:
    def test_within_range(self):
        assert _clamp(50) == 50

    def test_below_lo(self):
        assert _clamp(-10) == 0

    def test_above_hi(self):
        assert _clamp(150) == 100

    def test_custom_range(self):
        assert _clamp(5, 10, 90) == 10
        assert _clamp(95, 10, 90) == 90


class TestPercentileRank:
    def test_median_value(self):
        series = pd.Series(range(100))
        rank = _percentile_rank(series, 50, 100)
        assert 0.49 <= rank <= 0.51

    def test_min_value(self):
        series = pd.Series(range(100))
        rank = _percentile_rank(series, 0, 100)
        assert rank == 0.0

    def test_max_value(self):
        series = pd.Series(range(100))
        rank = _percentile_rank(series, 99, 100)
        assert rank == 0.99

    def test_insufficient_data(self):
        series = pd.Series([1, 2, 3])
        rank = _percentile_rank(series, 2, 100)  # only 3 values, need 50
        assert rank == 0.5  # neutral fallback


class TestCalcPctB:
    def test_at_lower_band(self):
        assert _calc_pct_b(100, 120, 100) == pytest.approx(0.0)

    def test_at_upper_band(self):
        assert _calc_pct_b(120, 120, 100) == pytest.approx(1.0)

    def test_at_middle(self):
        assert _calc_pct_b(110, 120, 100) == pytest.approx(0.5)

    def test_equal_bands(self):
        assert _calc_pct_b(100, 100, 100) == 0.5


class TestMapStatus:
    def test_extreme_fear(self):
        label, action = _map_status(3)
        assert label == "极端恐慌"

    def test_neutral(self):
        label, action = _map_status(50)
        assert label == "中性"

    def test_extreme_greed(self):
        label, action = _map_status(90)
        assert label == "极度贪婪"


# ── 维度评分测试 ──────────────────────────────────────────────────────────────


class TestScoreDailyTech:
    def test_returns_score_and_breakdown(self):
        spy = _make_daily_df(260, seed=1)
        qqq = _make_daily_df(260, seed=2)
        result = _score_daily_tech(spy, qqq)
        assert "score" in result
        assert "breakdown" in result
        assert 0 <= result["score"] <= 100

    def test_extreme_rsi_low(self):
        """RSI=5 should produce score=0 for that component (tiered: <10→0)."""
        spy = _make_daily_df(260)
        spy.iloc[-1, spy.columns.get_loc("rsi6")] = 5
        qqq = _make_daily_df(260)
        qqq.iloc[-1, qqq.columns.get_loc("rsi6")] = 5
        result = _score_daily_tech(spy, qqq)
        # RSI scores=0, but MACD/BB are random, so overall score drops below 50
        assert result["score"] < 50




# ── 仓位公式测试 ──────────────────────────────────────────────────────────────


class TestPositionFormula:
    def test_neutral_composite(self):
        """Composite=50 → target = 90 - 50*0.8 = 50%"""
        target = _clamp(90 - 50 * 0.8, 10, 90)
        assert target == 50.0

    def test_max_greed(self):
        """Composite=100 → target = 90 - 100*0.8 = 10%"""
        target = _clamp(90 - 100 * 0.8, 10, 90)
        assert target == 10.0

    def test_max_fear(self):
        """Composite=0 (normal) → target = 90 - 0 = 90%"""
        target = _clamp(90 - 0 * 0.8, 10, 90)
        assert target == 90.0

    def test_extreme_triggered(self):
        """Composite=5, extreme → target = 90 + (15-5)*2 = 110%"""
        target = _clamp(90 + (15 - 5) * 2, 90, 120)
        assert target == 110.0


# ── 集成测试 ──────────────────────────────────────────────────────────────────


class TestCalculateMarketTemperature:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        """用合成数据初始化临时数据库。"""
        storage.init_db()
        # 写入 SPY/QQQ/GLD/VIX 日线和周线
        for code, seed in [("US.SPY", 10), ("US.QQQ", 20), ("US.GLD", 30), ("US.VIXY", 40)]:
            daily = _make_daily_df(260, base_price=500 if code != "US.VIXY" else 25, seed=seed, for_storage=True)
            if code == "US.VIXY":
                daily["close"] = 20 + np.random.default_rng(seed).uniform(0, 15, 260)
            storage.batch_upsert(code, "1d", daily)

        for code, seed in [("US.SPY", 11), ("US.QQQ", 21)]:
            weekly = _make_weekly_df(60, seed=seed, for_storage=True)
            storage.batch_upsert(code, "1w", weekly)

    def test_returns_expected_structure(self):
        result = calculate_market_temperature()
        assert "composite_score" in result
        assert "target_position_pct" in result
        assert "extreme_triggered" in result
        assert "dimensions" in result
        assert "indicators" in result
        assert "market_status" in result
        assert "action_suggestion" in result
        assert 0 <= result["composite_score"] <= 100
        assert 10 <= result["target_position_pct"] <= 120
        assert len(result["dimensions"]) == 3

    def test_persists_to_storage(self):
        calculate_market_temperature()
        stored = storage.query_latest_market_score()
        assert stored
        assert "composite_score" in stored
        assert "detail" in stored

    def test_history_query(self):
        calculate_market_temperature()
        history = storage.query_market_score_history(30)
        assert len(history) >= 1
        assert "composite_score" in history[0]

    def test_no_data_returns_neutral(self, tmp_path, monkeypatch):
        """无数据时所有维度 fallback 为 50，综合也≈50。"""
        # 使用一个全新的空数据库（fixture 已写入合成数据，这里需要空库）
        empty_db = str(tmp_path / "empty.db")
        monkeypatch.setattr("trader_analysis.futu_strategy.config.DB_PATH", empty_db)
        storage.init_db()

        result = calculate_market_temperature()
        assert 45 <= result["composite_score"] <= 55
