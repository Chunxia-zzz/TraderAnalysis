"""FastAPI 端点测试。"""

import os

import pytest
from fastapi.testclient import TestClient

from trader_analysis.futu_strategy import storage, watchlist_storage
from trader_analysis.futu_strategy.api_server import app


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch, tmp_path):
    """全部测试用临时库 + 预置一条标的，不依赖本地 data/indicators.db（CI 全新 checkout 可跑）。"""
    db_path = str(tmp_path / "test_api.db")
    monkeypatch.setattr("trader_analysis.futu_strategy.config.DB_PATH", db_path)
    storage.init_db()
    watchlist_storage.init_watchlist_table()
    watchlist_storage.add_stock(
        {
            "code": "US.AAPL",
            "name": "Apple Inc.",
            "market": "US",
            "category": "科技",
            "status": "watching",
        }
    )


@pytest.fixture()
def client():
    """带 lifespan 的 TestClient：startup 钩子里会 init_db 建表。"""
    with TestClient(app) as c:
        yield c


def test_watchlist_returns_structure(client):
    resp = client.get("/api/watchlist")
    assert resp.status_code == 200
    data = resp.json()
    assert "categories" in data
    assert "watchlist" in data
    assert isinstance(data["watchlist"], list)
    assert len(data["watchlist"]) > 0
    # 每个标的应有 code 和 has_data 字段（v2.6 起用 code 替代 futu_code）
    item = data["watchlist"][0]
    assert "code" in item
    assert "has_data" in item
    assert "name" in item
    assert "category" in item
    # v3 新增：晨星折价与最新收盘价
    assert "latest_close" in item
    assert "ms_discount_pct" in item


def test_indicators_not_found(client):
    resp = client.get("/api/indicators", params={"code": "US.FAKECODE", "ktype": "1d"})
    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data
    assert "暂无" in data["message"]
    assert data["data"] == []


def test_indicators_latest_not_found(client):
    resp = client.get("/api/indicators/latest", params={"code": "US.FAKECODE"})
    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data
    assert data["data"] is None


def test_scores_latest_not_found(client):
    resp = client.get("/api/scores/latest", params={"code": "US.FAKECODE"})
    assert resp.status_code == 200
    assert "message" in resp.json()
    assert resp.json()["data"] is None


def test_indicators_invalid_ktype(client):
    resp = client.get("/api/indicators", params={"code": "US.AAPL", "ktype": "5m"})
    assert resp.status_code == 422  # validation error
