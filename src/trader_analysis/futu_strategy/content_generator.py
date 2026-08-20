"""自媒体文案生成器。

根据交易信号（daily-picks 的道氏趋势 + 估值数据），
生成不同平台（小红书 / 知乎 / 公众号）的发布文案。

设计原则：
- 纯模板渲染，不依赖 LLM，页面可即时生成、零成本
- 三套模板「大体相同、细节不同」，适配各平台风格与审核机制
- 数据与文案分离：先 build_summary 生成中文摘要，再填充模板

字段来源：daily-picks 单条结果（code/score/close/morningstar/discount_pct/
tide/wave/ripple_rsi/signal/trade_hint）+ 名称 + 分析师目标价。
"""

from __future__ import annotations


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
    """把 pick 数据转成中文摘要，供各平台模板复用。"""
    code = pick.get("code", "")
    ticker = code.split(".")[-1] if "." in code else code
    discount = pick.get("discount_pct")
    discount_text = f"{discount}%" if discount is not None else "—"

    upside = None
    if analyst_target and pick.get("close"):
        upside = round((analyst_target - pick["close"]) / pick["close"] * 100, 1)

    return {
        "ticker": ticker,
        "name": name or ticker,
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


# ── 小红书 ────────────────────────────────────────────────────────────────────


def _gen_xiaohongshu(s: dict) -> dict:
    title = f"量化系统今天只选出这1只，折价{s['discount_text']}"

    body = (
        f"跑了 196 只股票，我的系统今天只留下了 1 只 👇\n\n"
        f"{s['ticker']} · {s['name']}\n"
        f"评分 {s['score']}/100，全场最高\n\n"
        f"💰 晨星公允价值 ${s['morningstar']}\n"
        f"📉 现价才 ${s['close']}\n"
        f"折价 {s['discount_text']}，市场给打了骨折\n\n"
        f"📊 道氏三层：\n"
        f"潮汐（周线）{s['tide_text']}\n"
        f"波浪（日线）{s['wave_text']}\n"
        f"涟漪 {s['rsi_text']}\n\n"
        f"系统策略：{s['signal']}\n"
        f"{s['trade_hint']}\n\n"
        f"⚠️ 折价大 ≠ 必涨，市场可能看到了我没看到的利空\n\n"
        f"系统输出，不构成投资建议，理性参考"
    )

    hashtags = ["量化交易", "价值投资", s["ticker"], "道氏理论", "股票分析"]
    return {"title": title, "body": body, "hashtags": hashtags}


# ── 知乎 ──────────────────────────────────────────────────────────────────────


def _gen_zhihu(s: dict) -> dict:
    title = f"196 只股票，我的量化系统为什么只留下 {s['ticker']}？"

    analyst_line = ""
    if s["analyst_target"]:
        analyst_line = (
            f"\n2. 分析师一致目标价 ${s['analyst_target']}，"
            f"上行空间 {s['upside']}%（华尔街共识）"
        )

    body = (
        f"先说结论：{s['ticker']}（{s['name']}）是我这套量化系统在 {s['date']} "
        f"唯一选出的标的。\n\n"
        f"## 筛选逻辑（巴菲特三原则）\n"
        f"好公司：晨星公允价值 ${s['morningstar']}，现价 ${s['close']}，"
        f"折价 {s['discount_text']}\n"
        f"好位置：{s['tide_text']}，{s['wave_text']}\n"
        f"好价格：6 因子评分 {s['score']}/100，全场最高\n\n"
        f"## 三个值得注意的数据\n"
        f"1. 折价 {s['discount_text']} —— 晨星 DCF 给 ${s['morningstar']}，"
        f"市场只给 ${s['close']}"
        f"{analyst_line}\n"
        f"3. {s['rsi_text']}\n"
        f"4. 系统策略信号：{s['signal']}\n\n"
        f"## 但我必须泼一盆冷水\n"
        f"折价 {s['discount_text']} 不是「稳赚」，它更可能是市场对利空的定价。\n"
        f"分歧越大，越要问一句：市场知道什么是我不知道的？\n\n"
        f"（量化系统输出，案例复盘，不构成任何投资建议）"
    )

    return {"title": title, "body": body, "hashtags": []}


# ── 公众号 ────────────────────────────────────────────────────────────────────


def _gen_gongzhonghao(s: dict) -> dict:
    title = f"196 只股票，我的系统只留下了这 1 只"

    body = (
        f"今天是 {s['date']}，我照例跑了一遍量化评分系统。\n\n"
        f"196 只股票，最终只有 1 只通过了全部筛选。\n\n"
        f"它就是——{s['ticker']}（{s['name']}）。\n\n"
        f"01 / 为什么是它\n"
        f"三个条件同时满足：\n"
        f"好公司：晨星公允价值 ${s['morningstar']}，现价 ${s['close']}，"
        f"折价 {s['discount_text']}\n"
        f"好位置：{s['tide_text']}\n"
        f"好价格：6 因子评分 {s['score']}/100，全场最高\n\n"
        f"02 / 关键数据\n"
        f"折价 {s['discount_text']}，{s['rsi_text']}，"
        f"系统策略信号「{s['signal']}」。\n"
        f"{s['trade_hint']}\n\n"
        f"03 / 风险在哪\n"
        f"折价大不代表必涨。市场给出 {s['discount_text']} 的折扣，"
        f"大概率是定价了某些利空。分歧越大，越要谨慎。\n\n"
        f"写在最后\n"
        f"本文是个人量化系统的案例复盘，不构成投资建议。"
    )

    return {"title": title, "body": body, "hashtags": []}


# ── 主入口 ────────────────────────────────────────────────────────────────────

_GENERATORS = {
    "xiaohongshu": _gen_xiaohongshu,
    "zhihu": _gen_zhihu,
    "gongzhonghao": _gen_gongzhonghao,
}

PLATFORM_LABELS = {
    "xiaohongshu": "小红书",
    "zhihu": "知乎",
    "gongzhonghao": "公众号",
}


def generate(pick: dict, name: str = "", analyst_target=None) -> dict:
    """生成所有平台文案。

    Args:
        pick: daily-picks 单条结果
        name: 标的名称（中文名）
        analyst_target: 分析师一致目标价（可选）

    Returns:
        {"xiaohongshu": {...}, "zhihu": {...}, "gongzhonghao": {...}}
    """
    s = build_summary(pick, name, analyst_target)
    result = {}
    for key, fn in _GENERATORS.items():
        result[key] = fn(s)
        result[key]["platform"] = key
        result[key]["platform_label"] = PLATFORM_LABELS[key]
    return result


def generate_single(pick: dict, platform: str, name: str = "", analyst_target=None) -> dict:
    """生成单个平台的文案。"""
    fn = _GENERATORS.get(platform)
    if fn is None:
        raise ValueError(f"未知平台: {platform}，可选 {list(_GENERATORS)}")
    s = build_summary(pick, name, analyst_target)
    out = fn(s)
    out["platform"] = platform
    out["platform_label"] = PLATFORM_LABELS.get(platform, platform)
    return out
