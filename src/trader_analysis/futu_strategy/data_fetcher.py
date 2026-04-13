"""K 线数据获取。

封装富途实时 API 调用，对外暴露 fetch_daily / fetch_weekly 两个函数。
所有数据均通过 FutuLiveDataProvider 拉取并经 normalize_ohlcv 标准化。
"""

from __future__ import annotations

import logging

import pandas as pd

from trader_analysis.data.providers import DataProviderError, FutuLiveDataProvider
from trader_analysis.futu_strategy import config

logger = logging.getLogger(__name__)

_provider = FutuLiveDataProvider()


def check_kl_quota(quote_ctx, code_list: list[str]) -> None:
    """检查历史 K 线剩余额度，不足时抛出 RuntimeError。

    每个标的需消耗 2 个额度（日线 + 周线），在循环开始前统一检查一次。
    """
    ret, quota = quote_ctx.get_history_kl_quota(get_detail=False)
    if ret != 0:
        raise RuntimeError(f"获取 K 线额度失败: {quota}")

    # quota 可能是 DataFrame 或 dict，统一取 remain_count
    if hasattr(quota, "iloc"):
        remain = int(quota["remain_count"].iloc[0])
    else:
        remain = int(quota.get("remain_count", 0))

    needed = len(code_list) * 2
    if remain < needed:
        raise RuntimeError(
            f"历史 K 线额度不足：剩余 {remain} 个，本次需要 {needed} 个"
            f"（{len(code_list)} 个标的 × 日线+周线）"
        )
    logger.info(f"K 线额度检查通过：剩余 {remain}，需要 {needed}")


def fetch_daily(quote_ctx, code: str) -> pd.DataFrame:
    """拉取指定标的的日线 K 线（根数由 config.DAILY_KLINE_COUNT 控制）。"""
    try:
        return _provider.get_daily(quote_ctx, code, count=config.DAILY_KLINE_COUNT)
    except DataProviderError as exc:
        raise RuntimeError(f"拉取 {code} 日线失败: {exc}") from exc


def fetch_weekly(quote_ctx, code: str) -> pd.DataFrame:
    """拉取指定标的的周线 K 线（根数由 config.WEEKLY_KLINE_COUNT 控制）。"""
    try:
        return _provider.get_weekly(quote_ctx, code, count=config.WEEKLY_KLINE_COUNT)
    except DataProviderError as exc:
        raise RuntimeError(f"拉取 {code} 周线失败: {exc}") from exc
