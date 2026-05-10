"""富途股票信息获取与选股接口。

封装 get_stock_basicinfo / get_market_snapshot / get_stock_filter，
用于新增标的时自动填充和条件选股。OpenD 离线时优雅降级。
"""

from __future__ import annotations

import logging

from trader_analysis.futu_strategy import config

logger = logging.getLogger(__name__)


class OpenDNotConnected(Exception):
    """OpenD 连接失败。"""


def _get_quote_ctx():
    """创建 OpenQuoteContext，连接失败抛 OpenDNotConnected。"""
    try:
        from futu import OpenQuoteContext  # type: ignore[import]
    except ImportError:
        raise OpenDNotConnected("futu-api 未安装")

    try:
        ctx = OpenQuoteContext(host=config.OPEND_HOST, port=config.OPEND_PORT)
        return ctx
    except Exception as exc:
        raise OpenDNotConnected(f"无法连接 OpenD: {exc}") from exc


def fetch_stock_info(code: str) -> dict | None:
    """获取单只股票基础信息 + 快照数据。

    返回 dict 包含 name, sector, industry, listing_date, market_cap 等。
    OpenD 离线时返回 None。
    """
    try:
        ctx = _get_quote_ctx()
    except OpenDNotConnected:
        logger.warning("OpenD 未连接，跳过股票信息获取: %s", code)
        return None

    try:
        from futu import RET_OK  # type: ignore[import]

        # 获取基础信息
        from futu import Market as FutuMarket  # type: ignore[import]

        market_code = code.split(".")[0] if "." in code else "US"
        market_map = {"US": FutuMarket.US, "HK": FutuMarket.HK, "SH": FutuMarket.SH, "SZ": FutuMarket.SZ}
        futu_market = market_map.get(market_code, FutuMarket.US)
        ret, data = ctx.get_stock_basicinfo(futu_market, code_list=[code])
        info: dict = {}
        if ret == RET_OK and not data.empty:
            row = data.iloc[0]
            info["name"] = str(row.get("name", ""))
            info["sector"] = str(row.get("sec_type", "")) if row.get("sec_type") else None
            info["industry"] = str(row.get("industry", "")) if row.get("industry") else None
            info["listing_date"] = str(row.get("listing_date", "")) if row.get("listing_date") else None

        # 获取实时快照
        ret, snapshot = ctx.get_market_snapshot([code])
        if ret == RET_OK and not snapshot.empty:
            snap = snapshot.iloc[0]
            info["trailing_pe"] = _safe_float(snap.get("pe_ttm"))
            info["market_cap"] = _safe_float(snap.get("market_val"))
            info["current_price"] = _safe_float(snap.get("last_price"))
            info["dividend_yield"] = _safe_float(snap.get("dividend_yield"))
            info["beta"] = None  # 富途快照无 beta 字段

        return info if info else None
    except Exception as exc:
        logger.warning("获取股票信息失败 %s: %s", code, exc)
        return None
    finally:
        ctx.close()


def search_stocks(
    market: str = "US",
    min_market_cap: float | None = None,
    max_pe: float | None = None,
    min_price: float | None = None,
    sector: str | None = None,
) -> list[dict]:
    """条件选股。OpenD 离线时抛 OpenDNotConnected。"""
    ctx = _get_quote_ctx()  # 不捕获，让调用方处理

    try:
        from futu import (  # type: ignore[import]
            RET_OK,
            FilterType,
            Market,
            SimpleFilter,
            StockFilter,
        )

        # 构建筛选条件
        filter_list = []

        market_map = {"US": Market.US, "HK": Market.HK}
        futu_market = market_map.get(market.upper(), Market.US)

        if min_market_cap is not None:
            # 富途市值单位为元，输入为亿美元
            f = SimpleFilter()
            f.stock_field = StockFilter.StockField.MARKET_VAL
            f.filter_min = min_market_cap * 1e8
            filter_list.append(f)

        if max_pe is not None:
            f = SimpleFilter()
            f.stock_field = StockFilter.StockField.PE_TTM
            f.filter_max = max_pe
            f.is_no_filter = False
            filter_list.append(f)

        if min_price is not None:
            f = SimpleFilter()
            f.stock_field = StockFilter.StockField.CUR_PRICE
            f.filter_min = min_price
            filter_list.append(f)

        ret, ls = ctx.get_stock_filter(
            market=futu_market,
            filter_list=filter_list,
            begin=0,
            num=200,
        )
        if ret != RET_OK:
            logger.warning("条件选股失败: %s", ls)
            return []

        results = []
        for _, row in ls.iterrows():
            results.append({
                "code": str(row.get("stock_code", "")),
                "ticker": str(row.get("stock_code", "")).split(".")[-1],
                "name": str(row.get("stock_name", "")),
                "market": market.upper(),
                "sector": sector,
                "industry": None,
                "market_cap": _safe_float(row.get("market_val")),
                "trailing_pe": _safe_float(row.get("pe_ttm")),
                "current_price": _safe_float(row.get("cur_price")),
            })
        return results
    except OpenDNotConnected:
        raise
    except Exception as exc:
        logger.warning("条件选股异常: %s", exc)
        return []
    finally:
        ctx.close()


def fetch_snapshot_batch(codes: list[str]) -> dict[str, dict]:
    """批量获取快照数据。返回 {code: snapshot_dict}。"""
    try:
        ctx = _get_quote_ctx()
    except OpenDNotConnected:
        logger.warning("OpenD 未连接，跳过快照刷新")
        return {}

    try:
        from futu import RET_OK  # type: ignore[import]

        results = {}
        # 富途每次最多 400 只
        batch_size = 200
        for i in range(0, len(codes), batch_size):
            batch = codes[i : i + batch_size]
            ret, snapshot = ctx.get_market_snapshot(batch)
            if ret != RET_OK:
                logger.warning("批量快照获取失败: %s", snapshot)
                continue
            for _, row in snapshot.iterrows():
                code = str(row.get("code", ""))
                results[code] = {
                    "trailing_pe": _safe_float(row.get("pe_ttm")),
                    "market_cap": _safe_float(row.get("market_val")),
                    "current_price": _safe_float(row.get("last_price")),
                    "dividend_yield": _safe_float(row.get("dividend_yield")),
                    "beta": None,
                }
        return results
    except Exception as exc:
        logger.warning("批量快照异常: %s", exc)
        return {}
    finally:
        ctx.close()


def _safe_float(val) -> float | None:
    """安全转 float，无效值返回 None。"""
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN check
            return None
        return f
    except (ValueError, TypeError):
        return None
