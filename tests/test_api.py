"""FastAPI 端点测试。"""

import pytest
from fastapi.testclient import TestClient

from trader_analysis.futu_strategy.api_server import app

client = TestClient(app)


def test_watchlist_returns_structure():
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


def test_indicators_not_found():
    resp = client.get("/api/indicators", params={"code": "US.FAKECODE", "ktype": "1d"})
    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data
    assert "暂无" in data["message"]
    assert data["data"] == []


def test_indicators_latest_not_found():
    resp = client.get("/api/indicators/latest", params={"code": "US.FAKECODE"})
    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data
    assert data["data"] is None


def test_scores_latest_not_found():
    resp = client.get("/api/scores/latest", params={"code": "US.FAKECODE"})
    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data
    assert data["data"] is None


def test_indicators_invalid_ktype():
    resp = client.get("/api/indicators", params={"code": "US.AAPL", "ktype": "5m"})
    assert resp.status_code == 422  # validation error
