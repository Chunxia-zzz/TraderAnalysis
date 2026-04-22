"""核心模块导入测试。"""


def test_import_package():
    import trader_analysis
    assert trader_analysis.__version__ == "0.2.0"


def test_import_futu_strategy():
    from trader_analysis.futu_strategy import config
    assert isinstance(config.WATCHLIST, list)
    assert len(config.WATCHLIST) > 0


def test_import_providers():
    from trader_analysis.futu_strategy.providers import (
        DataProviderError,
        FutuLiveDataProvider,
        OHLCVSchema,
        normalize_ohlcv,
    )
    assert OHLCVSchema.timestamp == "timestamp"


def test_import_indicators():
    from trader_analysis.futu_strategy.indicators import calc_indicators  # noqa: F401


def test_import_scorer():
    from trader_analysis.futu_strategy.scorer import calculate_score  # noqa: F401


def test_import_storage():
    from trader_analysis.futu_strategy.storage import init_db, list_codes  # noqa: F401


def test_import_api():
    from trader_analysis.futu_strategy.api_server import app
    assert app.title == "Strategy Indicators API"
