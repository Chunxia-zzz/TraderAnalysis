"""标的池读取（SQLite 唯一数据源）与 Futu 代码格式测试。

标的池的唯一权威来源是 SQLite `watchlist` 表；`data/watchlist.json` 已于
2026-11-01 删除，代码中不再有 JSON 回退路径。数据库不存在或表为空时
（全新 clone / CI）跳过数据类断言，保证导入层面的测试仍可运行。
"""

import pytest

from trader_analysis.futu_strategy import config

_CODES = config.get_watchlist()
_needs_data = pytest.mark.skipif(
    not _CODES, reason="本地无数据库或 watchlist 表为空，跳过数据断言"
)


def test_watchlist_is_list():
    assert isinstance(config.WATCHLIST, list)


@_needs_data
def test_watchlist_loaded():
    assert len(_CODES) > 0


@_needs_data
def test_futu_code_format():
    for code in _CODES:
        parts = code.split(".")
        assert len(parts) >= 2, f"代码格式错误: {code}"
        assert parts[0] in ("US", "HK"), f"未知市场: {parts[0]}"


@_needs_data
def test_watchlist_detail_has_futu_code():
    for item in config.get_watchlist_detail():
        assert "futu_code" in item
        assert "ticker" in item
        assert "name" in item
        assert "market" in item
        assert "category" in item


@_needs_data
def test_categories_from_db():
    cats = config.get_categories()
    assert isinstance(cats, dict)
    assert len(cats) > 0
    assert all(isinstance(v, str) and v for v in cats.values())


@_needs_data
def test_watchlist_contains_known_code():
    codes = set(config.WATCHLIST)
    assert "US.AAPL" in codes
    assert len(codes) >= 100  # 标的池已扩充至 195 只
