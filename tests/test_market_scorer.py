"""市场温度评分模块单元测试。

2026-10-19 口径镜像反转后更新：
  - 新口径：分数越高 = 越恐慌 = 越值得加仓（与个股评分 total_score 同向）
  - 核心不变量：所有子项线性 → composite_new = 100 - composite_old，
    仓位映射与温度加成与旧口径逐位等价（TestMirrorEquivalence 验证）
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trader_analysis.futu_strategy import storage
from trader_analysis.futu_strategy.market_scorer import (
    NEUTRAL_SCORE,
    _calc_pct_b,
    _clamp,
    _compute_score,
    _map_position,
    _map_status,
    _percentile_rank,
    _score_asset_daily,
    _score_asset_price_position,
    _score_daily_tech,
    _score_price_position,
    _score_weekly_tech,
    calculate_market_temperature,
)
from trader_analysis.futu_strategy.scorer import calculate_score


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
    """新口径：高分=恐慌（>= 匹配），低分=贪婪。"""

    def test_extreme_fear(self):
        label, action = _map_status(97)
        assert label == "极端恐慌"
        assert action == "融资+期权超配"

    def test_heavy_fear(self):
        label, _ = _map_status(90)
        assert label == "极度恐慌"

    def test_neutral(self):
        label, action = _map_status(50)
        assert label == "中性"
        assert action == "维持仓位"

    def test_extreme_greed(self):
        label, action = _map_status(3)
        assert label == "极度贪婪"
        assert action == "大幅减仓"

    def test_boundary_values(self):
        """阈值边界：95/85/70/55/45/30/15/0 落入对应档位。"""
        expected = {
            95: "极端恐慌", 85: "极度恐慌", 70: "偏悲观", 55: "略偏冷",
            45: "中性", 30: "略偏热", 15: "偏贪婪", 0: "极度贪婪",
        }
        for score, label in expected.items():
            assert _map_status(score)[0] == label, f"score={score}"


class TestMapPosition:
    """仓位映射纯函数（高分=恐慌=高仓位）。"""

    def test_normal_range(self):
        """composite 0->75 映射到 30->85%。"""
        assert _map_position(0, False, False) == pytest.approx(30.0)
        assert _map_position(75, False, False) == pytest.approx(85.0)
        assert _map_position(50, False, False) == pytest.approx(30 + 50 * 55.0 / 75)

    def test_light_extreme(self):
        """composite 75->85 映射到 85->100%。"""
        assert _map_position(75, False, True) == pytest.approx(85.0)
        assert _map_position(85, False, True) == pytest.approx(100.0)

    def test_heavy_extreme(self):
        """composite 85->100 映射到 100->120%。"""
        assert _map_position(85, True, False) == pytest.approx(100.0)
        assert _map_position(100, True, False) == pytest.approx(120.0)
        assert _map_position(92.5, True, False) == pytest.approx(100 + 7.5 * 20.0 / 15)

    def test_mirror_equivalence_with_legacy(self):
        """与 2026-10-19 前旧口径逐位等价：new(100-c_old) == legacy(c_old)。

        旧公式（黄金参照）：
          heavy:  clamp(100 + (15 - c_old) * 20/15, 100, 120)
          light:  clamp(85 + (25 - c_old) * 1.5, 85, 100)
          normal: clamp(85 - (c_old - 25) * 55/75, 30, 85)
        """
        def legacy(c_old: float) -> float:
            if c_old <= 15:
                return _clamp(100 + (15 - c_old) * (20.0 / 15), 100, 120)
            if c_old <= 25:
                return _clamp(85 + (25 - c_old) * (15.0 / 10), 85, 100)
            return _clamp(85 - (c_old - 25) * (55.0 / 75), 30, 85)

        for c_old in np.arange(0, 100.5, 5):
            c_new = 100 - c_old
            is_heavy = c_new >= 85
            is_light = (c_new >= 75) and not is_heavy
            got = _map_position(c_new, is_heavy, is_light)
            assert got == pytest.approx(legacy(c_old)), f"c_old={c_old}"


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
        """新口径：RSI=5 极度超卖 → RSI 分项=100，整体分被拉高（>50）。"""
        spy = _make_daily_df(260)
        spy.iloc[-1, spy.columns.get_loc("rsi6")] = 5
        qqq = _make_daily_df(260)
        qqq.iloc[-1, qqq.columns.get_loc("rsi6")] = 5
        result = _score_daily_tech(spy, qqq)
        assert result["score"] > 50
        assert result["breakdown"]["SPY_RSI_score"] == 100.0

    def test_extreme_rsi_high(self):
        """新口径：RSI=95 极度超买 → 分档落在 90 档 → RSI 分项=10，整体分被压低（<50）。"""
        spy = _make_daily_df(260)
        spy.iloc[-1, spy.columns.get_loc("rsi6")] = 95
        qqq = _make_daily_df(260)
        qqq.iloc[-1, qqq.columns.get_loc("rsi6")] = 95
        result = _score_daily_tech(spy, qqq)
        assert result["score"] < 50
        assert result["breakdown"]["SPY_RSI_score"] == 10.0


# ── 镜像等价性（核心不变量）───────────────────────────────────────────────────


class TestMirrorEquivalence:
    """所有子项线性 → 新 composite = 100 - 旧 composite（旧公式内联为黄金参照）。"""

    def test_composite_mirror(self):
        spy_d = _make_daily_df(260, seed=1)
        qqq_d = _make_daily_df(260, seed=2)
        spy_w = _make_weekly_df(60, seed=11)
        qqq_w = _make_weekly_df(60, seed=12)

        new = _compute_score(spy_d, qqq_d, spy_w, qqq_w, "2026-10-16")["composite_score"]
        old = self._legacy_composite(spy_d, qqq_d, spy_w, qqq_w)
        # 生产值 round 到 1 位，容差取半位
        assert new == pytest.approx(100 - old, abs=0.051), f"new={new}, old={old}"

    def test_dimension_mirror(self):
        """三个维度分数也各自镜像。"""
        spy_d = _make_daily_df(260, seed=3)
        qqq_d = _make_daily_df(260, seed=4)
        spy_w = _make_weekly_df(60, seed=13)
        qqq_w = _make_weekly_df(60, seed=14)

        result = _compute_score(spy_d, qqq_d, spy_w, qqq_w, "2026-10-16")
        dims = {d["key"]: d["score"] for d in result["dimensions"]}
        old_daily, old_weekly, old_price = self._legacy_dimensions(spy_d, qqq_d, spy_w, qqq_w)
        assert dims["daily_tech"] == pytest.approx(100 - old_daily, abs=0.051)
        assert dims["weekly_tech"] == pytest.approx(100 - old_weekly, abs=0.051)
        assert dims["price_position"] == pytest.approx(100 - old_price, abs=0.051)

    # ── 旧口径参照实现（2026-10-19 反转前的公式，勿再改动）──

    @staticmethod
    def _legacy_pct(series: pd.Series, current: float, lookback: int) -> float:
        window = series.tail(lookback).dropna()
        if len(window) < 10:
            return 0.5
        return float((window < current).sum()) / len(window)

    @classmethod
    def _legacy_dimensions(cls, spy_d, qqq_d, spy_w, qqq_w):
        def daily(dfs):
            scores = []
            for df in dfs:
                last = df.iloc[-1]
                rsi = float(last.get("rsi6", 50))
                scores.append(_clamp(int(rsi / 10) * 10.0))
                macd_series = df["macd"].dropna()
                pct = cls._legacy_pct(macd_series, float(last.get("macd", 0)), 252)
                scores.append(pct * 100)
                c, u, l = (float(last.get(k, 0)) for k in ("close", "boll_upper", "boll_lower"))
                pct_b = 0.5 if (pd.isna(u) or pd.isna(l) or u == l) else (c - l) / (u - l)
                scores.append(_clamp(pct_b * 100))
            return sum(scores) / len(scores)

        def weekly(dfs):
            scores = []
            for df in dfs:
                last = df.iloc[-1]
                rsi = float(last.get("rsi6", 50))
                scores.append(_clamp(int(rsi / 10) * 10.0))
                macd_series = df["macd"].dropna()
                pct = cls._legacy_pct(macd_series, float(last.get("macd", 0)), 52)
                scores.append(pct * 100)
                c, u, l = (float(last.get(k, 0)) for k in ("close", "boll_upper", "boll_lower"))
                pct_b = 0.5 if (pd.isna(u) or pd.isna(l) or u == l) else (c - l) / (u - l)
                scores.append(_clamp(pct_b * 100))
            return sum(scores) / len(scores)

        def price(dfs):
            scores = []
            for df in dfs:
                cur = float(df.iloc[-1]["close"])
                r = df.tail(252)
                hi, lo = float(r["high"].max()), float(r["low"].min())
                pos = (cur - lo) / (hi - lo) if hi > lo else 0.5
                scores.append(_clamp(pos * 100))
                ath = float(df["high"].max())
                dd = (ath - cur) / ath if ath > 0 else 0
                scores.append(_clamp((1 - dd / 0.15) * 100))
                closes = df["close"].dropna()
                if len(closes) >= 200:
                    ma200 = float(closes.tail(200).mean())
                    dev = (cur - ma200) / ma200
                else:
                    dev = 0.0
                scores.append(_clamp((dev + 0.15) / 0.30 * 100))
            return sum(scores) / len(scores)

        old_daily = daily([spy_d, qqq_d])
        old_weekly = weekly([spy_w, qqq_w])
        old_price = price([spy_d, qqq_d])
        return old_daily, old_weekly, old_price

    @classmethod
    def _legacy_composite(cls, spy_d, qqq_d, spy_w, qqq_w) -> float:
        d, w, p = cls._legacy_dimensions(spy_d, qqq_d, spy_w, qqq_w)
        return d * 0.50 + w * 0.35 + p * 0.15


# ── 极端层与仓位集成（monkeypatch 精确控制 composite）─────────────────────────


class TestExtremeLayers:
    @staticmethod
    def _patch_dims(monkeypatch, score: float) -> None:
        from trader_analysis.futu_strategy import market_scorer

        stub = lambda *a, **k: {"score": score, "breakdown": {}}  # noqa: E731
        monkeypatch.setattr(market_scorer, "_score_daily_tech", stub)
        monkeypatch.setattr(market_scorer, "_score_weekly_tech", stub)
        monkeypatch.setattr(market_scorer, "_score_price_position", stub)

    @staticmethod
    def _frames(rsi: float = 50.0):
        spy_d = _make_daily_df(260, seed=1)
        qqq_d = _make_daily_df(260, seed=2)
        spy_w = _make_weekly_df(60, seed=11)
        qqq_w = _make_weekly_df(60, seed=12)
        for df in (spy_d, qqq_d, spy_w, qqq_w):
            df.iloc[-1, df.columns.get_loc("rsi6")] = rsi
        return spy_d, qqq_d, spy_w, qqq_w

    def test_heavy_extreme(self, monkeypatch):
        """composite>=85 且日/周 RSI<30 → heavy，仓位 100~120%，期权超配。"""
        self._patch_dims(monkeypatch, 90.0)
        result = _compute_score(*self._frames(rsi=5.0), score_date="2026-10-16")
        assert result["extreme_triggered"] is True
        assert result["extreme_level"] == "heavy"
        assert result["target_position_pct"] == pytest.approx(round(100 + 5 * 20.0 / 15, 1))
        assert result["leverage_tool"] == "margin + OTM_call"

    def test_heavy_guard_by_rsi(self, monkeypatch):
        """composite>=85 但 RSI 不低 → 降级 light（RSI 守卫生效）。"""
        self._patch_dims(monkeypatch, 90.0)
        result = _compute_score(*self._frames(rsi=50.0), score_date="2026-10-16")
        assert result["extreme_level"] == "light"
        assert result["target_position_pct"] == pytest.approx(100.0)
        assert result["leverage_tool"] == "margin"

    def test_light_extreme(self, monkeypatch):
        """composite 75~85 → light，仓位 85~100%。"""
        self._patch_dims(monkeypatch, 80.0)
        result = _compute_score(*self._frames(rsi=50.0), score_date="2026-10-16")
        assert result["extreme_level"] == "light"
        assert result["target_position_pct"] == pytest.approx(85 + 5 * 1.5)

    def test_normal_zone(self, monkeypatch):
        """composite<75 → 正常区，仓位 30~85%。"""
        self._patch_dims(monkeypatch, 50.0)
        result = _compute_score(*self._frames(rsi=50.0), score_date="2026-10-16")
        assert result["extreme_triggered"] is False
        assert result["extreme_level"] == "none"
        assert result["target_position_pct"] == pytest.approx(round(30 + 50 * 55.0 / 75, 1))
        assert result["leverage_tool"] == "none"

    def test_status_mirror(self, monkeypatch):
        """高分 → 恐慌文案；低分 → 贪婪文案。"""
        self._patch_dims(monkeypatch, 90.0)
        high = _compute_score(*self._frames(rsi=50.0), score_date="2026-10-16")
        assert high["market_status"] == "极度恐慌"
        assert high["action_suggestion"] == "重仓逆势买入"

        self._patch_dims(monkeypatch, 10.0)
        low = _compute_score(*self._frames(rsi=50.0), score_date="2026-10-16")
        assert low["market_status"] == "极度贪婪"
        assert low["action_suggestion"] == "大幅减仓"


# ── 单资产（GLD / BTC）────────────────────────────────────────────────────────


class TestAssetScoring:
    def test_asset_daily_rsi_direction(self):
        """新口径：RSI=5 → 分项 100；RSI=95 → 分档 90 档 → 分项 10。"""
        df = _make_daily_df(260, seed=7)
        cfg = {"ath_drawdown_zero": 0.25, "ma200_range": 0.20}

        df.iloc[-1, df.columns.get_loc("rsi6")] = 5
        assert _score_asset_daily(df, cfg)["breakdown"]["daily_rsi_score"] == 100.0

        df.iloc[-1, df.columns.get_loc("rsi6")] = 95
        assert _score_asset_daily(df, cfg)["breakdown"]["daily_rsi_score"] == 10.0

    def test_btc_ath_drawdown_direction(self):
        """新口径：回撤越深分越高。BTC 腰斩（回撤 ~50%）→ ATH 分项满分。"""
        n = 260
        df = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * (n - 1) + [50.0],
            "volume": [1e6] * n,
            "rsi6": [50.0] * n,
            "macd": [0.0] * n,
            "boll_upper": [110.0] * n,
            "boll_lower": [90.0] * n,
            "vol_ma20": [1e6] * n,
        })
        cfg = {"ath_drawdown_zero": 0.50, "ma200_range": 0.60}
        result = _score_asset_price_position(df, cfg)
        assert result["breakdown"]["ath_score"] == 100.0
        assert result["breakdown"]["ath_drawdown"] > 0.49


# ── 个股评分温度加成（scorer.py 联动）─────────────────────────────────────────


class TestMarketBonus:
    @staticmethod
    def _minimal_frames():
        n = 30
        daily = pd.DataFrame({
            "close": np.linspace(100, 90, n),
            "high": np.linspace(101, 91, n),
            "low": np.linspace(99, 89, n),
            "rsi6": [50.0] * n,
            "macd": np.linspace(-1, -2, n),
            "boll_upper": [110.0] * n,
            "boll_lower": [85.0] * n,
        })
        weekly = pd.DataFrame({
            "rsi6": [50.0] * 12,
            "macd": np.linspace(-1, -2, 12),
        })
        return daily, weekly

    def _bonus(self, market_composite):
        daily, weekly = self._minimal_frames()
        return calculate_score("US.TEST", daily, weekly, market_composite=market_composite)["market_bonus"]

    def test_bonus_fires_on_high_panic(self):
        """新口径：composite > 60（恐慌）触发加成。"""
        assert self._bonus(70) == pytest.approx(3.8)
        assert self._bonus(100) == pytest.approx(15.0)

    def test_no_bonus_on_greed(self):
        """新口径：composite <= 60（贪婪/中性）不加成。"""
        for c in (0, 30, 50, 60):
            assert self._bonus(c) == 0.0, f"composite={c}"

    def test_no_bonus_on_none(self):
        assert self._bonus(None) == 0.0

    def test_mirror_equivalence_with_legacy(self):
        """加成值与旧口径逐位等价：bonus_new(100-c_old) == bonus_old(c_old)。

        旧公式：(40 - c_old) / 40 * 15（c_old < 40 时）。
        """
        def legacy(c_old: float) -> float:
            if c_old < 40:
                return round(_clamp((40 - c_old) / 40) * 15, 1)
            return 0.0

        for c_old in (0, 10, 20, 25, 30, 35, 39.9, 40, 50, 60, 80, 100):
            c_new = 100 - c_old
            assert self._bonus(c_new) == pytest.approx(legacy(c_old)), f"c_old={c_old}"


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
