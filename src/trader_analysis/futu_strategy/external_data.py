"""外部数据获取：VIX 和 CNN Fear & Greed 指数。

VIX：通过富途 get_market_snapshot 获取，与标的数据同源。
CNN F&G：通过 HTTP 请求 CNN 非官方接口，整次运行只拉取一次（模块级缓存）。
任一来源失败均记录警告并返回 None，不中断整体评分流程。
"""

from __future__ import annotations

import logging

import requests

from trader_analysis.futu_strategy import config

logger = logging.getLogger(__name__)

# 模块级缓存：同一次运行中所有标的共用同一份 F&G 数据
_fg_cache: float | None = None


def get_vix(quote_ctx) -> float | None:
    """通过富途快照接口获取 VIX 当前价格。

    若获取失败返回 None，调用方将该项评分计为 0 分。
    """
    try:
        ret, df = quote_ctx.get_market_snapshot([config.VIX_CODE])
        if ret != 0:
            raise RuntimeError(f"快照接口返回错误: {df}")
        value = float(df["last_price"].iloc[0])
        logger.info(f"VIX = {value:.2f}")
        return value
    except Exception as exc:
        logger.warning(f"VIX 获取失败（{config.VIX_CODE}）: {exc}")
        return None


def get_fear_greed() -> float | None:
    """获取 CNN Fear & Greed 指数（0~100，越小越恐慌）。

    同一次运行中首次调用发起 HTTP 请求，后续调用直接返回缓存值。
    网络失败时返回 None，调用方将该项评分计为 0 分。
    """
    global _fg_cache
    if _fg_cache is not None:
        return _fg_cache

    try:
        resp = requests.get(
            config.CNN_FG_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=config.HTTP_TIMEOUT,
            proxies=config.HTTP_PROXIES,
        )
        resp.raise_for_status()
        score = float(resp.json()["fear_and_greed"]["score"])
        _fg_cache = score
        logger.info(f"CNN Fear & Greed = {score:.1f}")
        return score
    except Exception as exc:
        logger.warning(f"CNN Fear & Greed 获取失败: {exc}，该项计 0 分")
        return None


def reset_cache() -> None:
    """清空 F&G 缓存，每次策略运行开始前调用。"""
    global _fg_cache
    _fg_cache = None
