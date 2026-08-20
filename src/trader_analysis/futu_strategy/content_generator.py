"""自媒体文案生成器（模板化）。

根据交易信号（daily-picks 的道氏趋势 + 估值数据），
生成不同平台（小红书 / 知乎 / 公众号）的发布文案。

模板已抽离到 template_store.py 的 content_templates 表，
本模块只负责：build_summary 生成中文摘要 → 从 DB 读模板渲染。
"""

from __future__ import annotations

from trader_analysis.futu_strategy import template_store
from trader_analysis.futu_strategy.stock_names import get_cn_name


# ── 中文映射 ──────────────────────────────────────────────────────────────────

_TIDE_TEXT = {
    "up": "周线涨潮（MA20 站上 MA60，大趋势向上）",
    "down": "周线退潮（MA20 跌破 MA60，大趋势向下）",
    "neutral": "周线方向不明",
}

_WAVE_TEXT = {
    "up": "日线上升（MA20 站上 MA60）",
    "down": "日线回调（MA20 跌破 MA60）",
    "neutral": "日线方向不明",
}


def _rsi_text(rsi) -> str:
    if rsi is None:
        return "数据不足"
    if rsi < 30:
        return f"超卖（RSI {rsi}，短期抛压衰竭）"
    if rsi < 40:
        return f"偏弱（RSI {rsi}，处于回调区）"
    if rsi > 70:
        return f"超买（RSI {rsi}，短期过热）"
    return f"中性（RSI {rsi}）"


def build_summary(pick: dict, name: str = "", analyst_target=None) -> dict:
    """把 pick 数据转成中文摘要，供模板占位符复用。"""
    code = pick.get("code", "")
    ticker = code.split(".")[-1] if "." in code else code
    discount = pick.get("discount_pct")
    discount_text = f"{discount}%" if discount is not None else "—"

    upside = None
    if analyst_target and pick.get("close"):
        upside = round((analyst_target - pick["close"]) / pick["close"] * 100, 1)

    return {
        "ticker": ticker,
        "name": get_cn_name(ticker) or name or ticker,
        "code": code,
        "date": str(pick.get("date", "")),
        "score": pick.get("score"),
        "close": pick.get("close"),
        "morningstar": pick.get("morningstar"),
        "discount_pct": discount,
        "discount_text": discount_text,
        "tide_text": _TIDE_TEXT.get(pick.get("tide", ""), "方向不明"),
        "wave_text": _WAVE_TEXT.get(pick.get("wave", ""), "方向不明"),
        "rsi": pick.get("ripple_rsi"),
        "rsi_text": _rsi_text(pick.get("ripple_rsi")),
        "signal": pick.get("signal") or "观望",
        "trade_hint": pick.get("trade_hint") or "",
        "analyst_target": analyst_target,
        "upside": upside,
    }


PLATFORM_LABELS = {
    "xiaohongshu": "小红书",
    "zhihu": "知乎",
    "gongzhonghao": "公众号",
}

_PLATFORM_KEYS = {
    "xiaohongshu": "pick_xiaohongshu",
    "zhihu": "pick_zhihu",
    "gongzhonghao": "pick_gongzhonghao",
}


def _render_platform(platform: str, summary: dict) -> dict:
    key = _PLATFORM_KEYS[platform]
    tpl = template_store.get_template(key)
    return {
        "title": template_store.render(tpl["title"], summary),
        "body": template_store.render(tpl["body"], summary),
        "hashtags": [template_store.render(h, summary) for h in tpl.get("hashtags", [])],
        "platform": platform,
        "platform_label": PLATFORM_LABELS.get(platform, platform),
    }


def generate(pick: dict, name: str = "", analyst_target=None) -> dict:
    """生成所有平台文案。"""
    s = build_summary(pick, name, analyst_target)
    return {platform: _render_platform(platform, s) for platform in _PLATFORM_KEYS}


def generate_single(pick: dict, platform: str, name: str = "", analyst_target=None) -> dict:
    """生成单个平台的文案。"""
    if platform not in _PLATFORM_KEYS:
        raise ValueError(f"未知平台: {platform}，可选 {list(_PLATFORM_KEYS)}")
    return _render_platform(platform, build_summary(pick, name, analyst_target))
