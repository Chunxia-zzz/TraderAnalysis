"""市场温度 API 端点测试。"""

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


@pytest.mark.asyncio
async def test_market_temperature_not_found():
    """无数据时返回 200 + message。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/market-temperature")
    assert resp.status_code == 200
    assert "暂无市场温度数据" in resp.json()["message"]
    assert resp.json()["data"] is None


@pytest.mark.asyncio
async def test_market_temperature_history_empty():
    """历史为空时返回空列表。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/market-temperature/history?days=7")
    assert resp.status_code == 200
    assert resp.json()["history"] == []


@pytest.mark.asyncio
async def test_market_temperature_with_data():
    """插入数据后能正常返回。"""
    storage.upsert_market_score("2026-05-01", {
        "composite_score": 42.3,
        "target_position_pct": 56.2,
        "extreme_triggered": False,
        "leverage_tool": "none",
        "daily_tech_score": 38.5,
        "weekly_tech_score": 45.2,
        "vol_score": 52.1,
        "price_score": 35.8,
        "volume_score": 44.0,
        "safe_haven_score": 55.3,
        "spy_price": 5320.5,
        "qqq_price": 438.2,
        "gld_price": 312.5,
        "vix_value": 22.5,
        "spy_daily_rsi": 45.2,
        "qqq_daily_rsi": 42.8,
        "spy_weekly_rsi": 52.1,
        "qqq_weekly_rsi": 48.5,
        "spy_ma200_dev": -0.031,
        "qqq_ma200_dev": -0.052,
        "spy_vol_ratio": 1.2,
        "qqq_vol_ratio": 0.9,
        "detail": {"SPY_RSI": 45.2, "QQQ_RSI": 42.8},
    })

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/market-temperature")
    assert resp.status_code == 200
    data = resp.json()
    assert data["composite_score"] == 42.3
    assert data["target_position_pct"] == 56.2
    assert data["extreme_triggered"] is False


@pytest.mark.asyncio
async def test_market_temperature_history_with_data():
    """历史查询正常返回。"""
    storage.upsert_market_score("2026-05-01", {
        "composite_score": 42.3,
        "target_position_pct": 56.2,
        "extreme_triggered": False,
        "leverage_tool": "none",
        "detail": {},
    })
    storage.upsert_market_score("2026-05-02", {
        "composite_score": 44.1,
        "target_position_pct": 54.7,
        "extreme_triggered": False,
        "leverage_tool": "none",
        "detail": {},
    })

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/market-temperature/history?days=7")
    assert resp.status_code == 200
    history = resp.json()["history"]
    assert len(history) == 2
    # 升序（较早的在前）
    assert history[0]["date"] == "2026-05-01"
    assert history[1]["date"] == "2026-05-02"
