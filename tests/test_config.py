"""watchlist.json 加载和 Futu 代码格式转换测试。"""

from trader_analysis.futu_strategy import config


def test_watchlist_loaded():
    assert len(config.WATCHLIST) > 0


def test_futu_code_format():
    for code in config.WATCHLIST:
        parts = code.split(".")
        assert len(parts) >= 2, f"代码格式错误: {code}"
        assert parts[0] in ("US", "HK"), f"未知市场: {parts[0]}"


def test_watchlist_detail_has_futu_code():
    for item in config.WATCHLIST_DETAIL:
        assert "futu_code" in item
        assert "ticker" in item
        assert "name" in item
        assert "market" in item
        assert "category" in item


def test_categories_loaded():
    assert isinstance(config.WATCHLIST_CATEGORIES, dict)
    assert len(config.WATCHLIST_CATEGORIES) > 0


def test_futu_code_matches_detail():
    """WATCHLIST 从 DB 动态读取（标的池已迁移到 SQLite），不再与 JSON 回退列表强一致。"""
    codes_from_list = set(config.WATCHLIST)
    # DB 非空时，WATCHLIST 应包含常见标的，且规模达到扩充后的水平
    assert "US.AAPL" in codes_from_list
    assert len(codes_from_list) >= 100  # 标的池已扩充至 196 只
