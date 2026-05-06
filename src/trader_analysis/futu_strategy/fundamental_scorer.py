"""基本面多因子评分引擎。

5 维度加权评分，满分 100。与技术面评分（scorer.py）互补。
"""

from __future__ import annotations

from trader_analysis.futu_strategy import config


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _score_valuation_discount(current_price: float | None, target_mean: float | None) -> dict:
    """F1: 估值折价（权重 30）。目标价上行空间越大，得分越高。"""
    weight = config.FUNDAMENTAL_WEIGHTS["valuation_discount"]
    if not current_price or not target_mean or current_price <= 0:
        return {"score": 0.0, "raw": None, "ratio": None}
    upside = (target_mean - current_price) / current_price
    ratio = _clamp((upside + 0.10) / 0.40)  # -10%→0, +30%→1
    return {"score": round(ratio * weight, 1), "raw": round(upside, 4), "ratio": round(ratio, 3)}


def _score_pe_reasonability(forward_pe: float | None) -> dict:
    """F2: PE 合理性（权重 20）。Forward PE 越低，得分越高。"""
    weight = config.FUNDAMENTAL_WEIGHTS["pe_reasonability"]
    if forward_pe is None or forward_pe <= 0:
        return {"score": 0.0, "raw": forward_pe, "ratio": None}
    ratio = _clamp((40 - forward_pe) / 30)  # 10→1, 40→0
    return {"score": round(ratio * weight, 1), "raw": round(forward_pe, 2), "ratio": round(ratio, 3)}


def _score_growth(revenue_growth: float | None, earnings_growth: float | None) -> dict:
    """F3: 成长性（权重 20）。双增长越强，得分越高。"""
    weight = config.FUNDAMENTAL_WEIGHTS["growth"]
    rev_g = revenue_growth or 0
    earn_g = earnings_growth or 0
    if revenue_growth is None and earnings_growth is None:
        return {"score": 0.0, "raw": None, "ratio": None}
    combined = 0.5 * rev_g + 0.5 * earn_g
    ratio = _clamp(combined / 0.30)  # 0%→0, 30%→1
    return {"score": round(ratio * weight, 1), "raw": round(combined, 4), "ratio": round(ratio, 3)}


def _score_financial_health(
    roe: float | None, profit_margin: float | None, debt_to_equity: float | None
) -> dict:
    """F4: 财务健康（权重 15）。ROE高+利润率高+低负债。"""
    weight = config.FUNDAMENTAL_WEIGHTS["financial_health"]
    if roe is None and profit_margin is None and debt_to_equity is None:
        return {"score": 0.0, "raw": None, "ratio": None}

    roe_ratio = _clamp((roe or 0) / 0.20)
    pm_ratio = _clamp((profit_margin or 0) / 0.25)
    de_ratio = _clamp((200 - (debt_to_equity or 100)) / 150)

    avg_ratio = (roe_ratio + pm_ratio + de_ratio) / 3
    return {
        "score": round(avg_ratio * weight, 1),
        "raw": {"roe": roe, "profit_margin": profit_margin, "debt_to_equity": debt_to_equity},
        "ratio": round(avg_ratio, 3),
    }


def _score_analyst_consensus(recommendation: str | None, analyst_count: int | None) -> dict:
    """F5: 分析师共识（权重 15）。"""
    weight = config.FUNDAMENTAL_WEIGHTS["analyst_consensus"]
    if not recommendation and not analyst_count:
        return {"score": 0.0, "raw": None, "ratio": None}

    rec_map = {
        "strong_buy": 1.0, "buy": 0.75, "hold": 0.4,
        "underperform": 0.2, "sell": 0.1, "strong_sell": 0.0,
    }
    rec_score = rec_map.get(recommendation or "", 0.4)
    count = analyst_count or 0
    coverage = _clamp((count - 3) / 12) * 0.5 + 0.5  # 3→0.5, 15→1.0
    ratio = rec_score * coverage
    return {
        "score": round(ratio * weight, 1),
        "raw": recommendation,
        "ratio": round(ratio, 3),
    }


def calculate_fundamental_score(code: str, data: dict) -> dict:
    """汇总 5 个维度，返回评分结果。

    Args:
        code: 标的代码
        data: fundamental_fetcher 拉取的字段字典

    Returns:
        包含 fundamental_score, valuation_signal, breakdown 的结果 dict
    """
    f1 = _score_valuation_discount(data.get("current_price"), data.get("target_mean"))
    f2 = _score_pe_reasonability(data.get("forward_pe"))
    f3 = _score_growth(data.get("revenue_growth"), data.get("earnings_growth"))
    f4 = _score_financial_health(data.get("roe"), data.get("profit_margin"), data.get("debt_to_equity"))
    f5 = _score_analyst_consensus(data.get("recommendation"), data.get("analyst_count"))

    total = f1["score"] + f2["score"] + f3["score"] + f4["score"] + f5["score"]
    total = round(total, 1)

    # 信号映射
    if total >= config.FUNDAMENTAL_SIGNAL_UNDERVALUED:
        signal = "UNDERVALUED"
    elif total < config.FUNDAMENTAL_SIGNAL_OVERVALUED:
        signal = "OVERVALUED"
    else:
        signal = "FAIR"

    return {
        "fundamental_score": total,
        "valuation_signal": signal,
        "breakdown": {
            "valuation_discount": f1,
            "pe_reasonability": f2,
            "growth": f3,
            "financial_health": f4,
            "analyst_consensus": f5,
        },
    }
