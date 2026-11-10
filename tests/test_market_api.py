"""市场温度 API 端点测试（2026-11-10 起按指数拆分）。

契约要点：
  - 顶层不再有 composite_score / target_position_pct
  - indexes[] 每条自带 composite_score / target_position_pct
  - spread = SPY − QQQ，负值 = 标普相对更强
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from trader_analysis.futu_strategy import storage
from trader_analysis.futu_strategy.api_server import app


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch, tmp_path):
    """所有测试使用临时数据库，绝不触碰本地 indicators.db。"""
    db_path = str(tmp_path / "test_market_api.db")
    monkeypatch.setattr("trader_analysis.futu_strategy.config.DB_PATH", db_path)
    storage.init_db()


def _seed(date: str, code: str, score: float, position: float, level: str = "none") -> None:
    storage.upsert_market_temp_split(
        date,
        code,
        {
            "composite_score": score,
            "target_position_pct": position,
            "extreme_triggered": level != "none",
            "extreme_level": level,
            "leverage_tool": "none",
            "market_status": "偏悲观",
            "action_suggestion": "积极加仓",
            "dimensions": [
                {"key": "daily_tech", "label": "日线技术面", "score": score, "weight": 0.5},
                {"key": "weekly_tech", "label": "周线技术面", "score": score, "weight": 0.35},
                {"key": "price_position", "label": "价格位置", "score": score, "weight": 0.15},
            ],
            "indicators": {
                "price": 100.0,
                "daily_rsi": 50.0,
                "weekly_rsi": 50.0,
                "ma200_dev": 0.0,
                "ath_drawdown": 0.05,
                "pos_52w": 0.5,
            },
            "detail": {},
        },
    )


@pytest.mark.asyncio
async def test_market_temperature_not_found():
    """无数据时返回 200 + message。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/market-temperature")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] is None
    assert "指数温度" in body["message"]


@pytest.mark.asyncio
async def test_market_temperature_with_data():
    """插入数据后返回两个指数 + 温差，且顶层不再有全局分数。"""
    _seed("2026-05-01", "US.SPY", 70.3, 81.6)
    _seed("2026-05-01", "US.QQQ", 79.4, 91.6, level="light")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/market-temperature")
    assert resp.status_code == 200
    data = resp.json()

    # 契约：顶层不再暴露全局温度与全局仓位
    assert "composite_score" not in data
    assert "target_position_pct" not in data

    assert [i["key"] for i in data["indexes"]] == ["SPY", "QQQ"]
    spy, qqq = data["indexes"]
    assert spy["composite_score"] == 70.3
    assert qqq["composite_score"] == 79.4
    assert qqq["extreme_level"] == "light"
    assert data["spread"]["value"] == pytest.approx(-9.1)
    assert data["spread"]["label"] == "标普相对更强"
    assert len(spy["dimensions"]) == 3


@pytest.mark.asyncio
async def test_market_temperature_history_empty():
    """历史为空时返回空序列而非报错。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/market-temperature/history?days=7")
    assert resp.status_code == 200
    body = resp.json()
    assert body["spread"] == []
    assert all(s["points"] == [] for s in body["series"])


@pytest.mark.asyncio
async def test_market_temperature_history_with_data():
    """历史按日期升序返回两条序列，温差逐点等于 SPY − QQQ。"""
    for date, spy_score, qqq_score in [
        ("2026-05-01", 42.3, 44.1),
        ("2026-05-02", 48.0, 40.0),
    ]:
        _seed(date, "US.SPY", spy_score, 56.2)
        _seed(date, "US.QQQ", qqq_score, 54.7)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/market-temperature/history?days=7")
    assert resp.status_code == 200
    body = resp.json()

    spy_points = next(s for s in body["series"] if s["key"] == "SPY")["points"]
    qqq_points = next(s for s in body["series"] if s["key"] == "QQQ")["points"]
    assert [p["date"] for p in spy_points] == ["2026-05-01", "2026-05-02"]
    assert [p["date"] for p in qqq_points] == ["2026-05-01", "2026-05-02"]

    spread = body["spread"]
    assert len(spread) == 2
    assert spread[0]["value"] == pytest.approx(-1.8)
    assert spread[1]["value"] == pytest.approx(8.0)


@pytest.mark.asyncio
async def test_history_start_is_clamped_to_2025():
    """start 早于 2025-01-01 时一律夹到 2025-01-01（更早不做拆分回算）。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/market-temperature/history?start=2024-06-01")
    assert resp.status_code == 200
    assert resp.json()["start"] == "2025-01-01"
