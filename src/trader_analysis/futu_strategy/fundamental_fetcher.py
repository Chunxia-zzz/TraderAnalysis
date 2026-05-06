"""基本面数据获取层。

从 yfinance 批量拉取标的基本面数据（不依赖 Futu OpenD）。
"""

from __future__ import annotations

import logging
import time

from trader_analysis.futu_strategy import config

logger = logging.getLogger(__name__)

# yfinance info key → 内部字段名
_FIELD_MAP = {
    "currentPrice": "current_price",
    "regularMarketPrice": "current_price",
    "trailingPE": "trailing_pe",
    "forwardPE": "forward_pe",
    "trailingEps": "trailing_eps",
    "forwardEps": "forward_eps",
    "pegRatio": "peg_ratio",
    "priceToBook": "price_to_book",
    "enterpriseToEbitda": "ev_to_ebitda",
    "revenueGrowth": "revenue_growth",
    "earningsGrowth": "earnings_growth",
    "revenuePerShare": "revenue_per_share",
    "targetMeanPrice": "target_mean",
    "targetMedianPrice": "target_median",
    "targetHighPrice": "target_high",
    "targetLowPrice": "target_low",
    "numberOfAnalystOpinions": "analyst_count",
    "recommendationKey": "recommendation",
    "currentRatio": "current_ratio",
    "debtToEquity": "debt_to_equity",
    "freeCashflow": "free_cashflow",
    "operatingCashflow": "operating_cashflow",
    "profitMargins": "profit_margin",
    "grossMargins": "gross_margin",
    "returnOnEquity": "roe",
    "marketCap": "market_cap",
    "dividendYield": "dividend_yield",
    "beta": "beta",
    "shortRatio": "short_ratio",
}


def to_yfinance_symbol(code: str) -> str:
    """将 Futu 格式代码转为 yfinance symbol。

    US.AAPL → AAPL
    HK.07709 → 7709.HK
    """
    parts = code.split(".", 1)
    if len(parts) != 2:
        return code
    market, ticker = parts
    if market == "US":
        return ticker
    elif market == "HK":
        # 港股: 去前导零 + .HK
        return f"{int(ticker)}.HK" if ticker.isdigit() else f"{ticker}.HK"
    return ticker


def _extract_fields(info: dict) -> dict:
    """从 yfinance info dict 提取标准化字段。"""
    result = {}
    for yf_key, our_key in _FIELD_MAP.items():
        val = info.get(yf_key)
        if val is not None and our_key not in result:
            result[our_key] = _safe_number(val) if our_key != "recommendation" else str(val)
    return result


def _safe_number(val) -> float | None:
    """安全转浮点数。"""
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN
            return None
        return f
    except (ValueError, TypeError):
        return None


def fetch_single(code: str) -> dict | None:
    """拉取单只标的的基本面数据。返回字段 dict 或 None（失败/跳过）。"""
    import yfinance as yf

    ticker = code.split(".", 1)[-1] if "." in code else code
    if ticker in config.FUNDAMENTAL_SKIP_TICKERS:
        return None

    symbol = to_yfinance_symbol(code)
    for attempt in range(2):
        try:
            tk = yf.Ticker(symbol)
            info = tk.info or {}
            if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
                logger.warning("yfinance 无数据: %s (%s)", code, symbol)
                return None
            return _extract_fields(info)
        except Exception as exc:
            if "Rate" in str(exc) and attempt == 0:
                logger.info("限频，等待 30s 重试: %s", code)
                time.sleep(30)
                continue
            logger.warning("yfinance 拉取失败 %s: %s", code, exc)
            return None
    return None


def fetch_all(code_list: list[str]) -> list[dict]:
    """批量拉取基本面数据。

    返回: [{"code": "US.SNDK", "data": {...}}, ...]
    跳过/失败的标的不在列表中。
    """
    results = []
    for i, code in enumerate(code_list):
        ticker = code.split(".", 1)[-1] if "." in code else code
        if ticker in config.FUNDAMENTAL_SKIP_TICKERS:
            continue

        data = fetch_single(code)
        if data:
            results.append({"code": code, "data": data})

        # 限频
        if i < len(code_list) - 1:
            time.sleep(config.FUNDAMENTAL_FETCH_INTERVAL)

    return results
