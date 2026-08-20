"""市场复盘报告生成器。

生成「日复盘」和「周复盘」两份报告：
- 大盘：标普500 / 纳指 / 黄金 / 比特币
- 七姐妹（MAG7）：苹果 / 亚马逊 / 谷歌 / Meta / 微软 / 英伟达 / 特斯拉
- 交易机会：低估做多信号（放最后）

日复盘用日线（ktype=1d），周复盘用周线（ktype=1w）。
纯本地计算，不依赖 LLM，页面可即时生成。
"""

from __future__ import annotations

import pandas as pd

from trader_analysis.futu_strategy import storage, template_store


# ── 复盘标的 ──────────────────────────────────────────────────────────────────

REVIEW_ASSETS = [
    # 大盘
    {"code": "US.SPY", "label": "标普500", "group": "macro"},
    {"code": "US.QQQ", "label": "纳指", "group": "macro"},
    {"code": "US.GLD", "label": "黄金", "group": "macro"},
    {"code": "US.IBIT", "label": "比特币", "group": "macro"},
    # 七姐妹
    {"code": "US.AAPL", "label": "苹果", "group": "mag7"},
    {"code": "US.AMZN", "label": "亚马逊", "group": "mag7"},
    {"code": "US.GOOGL", "label": "谷歌", "group": "mag7"},
    {"code": "US.META", "label": "Meta", "group": "mag7"},
    {"code": "US.MSFT", "label": "微软", "group": "mag7"},
    {"code": "US.NVDA", "label": "英伟达", "group": "mag7"},
    {"code": "US.TSLA", "label": "特斯拉", "group": "mag7"},
]


# ── 单标的分析 ────────────────────────────────────────────────────────────────


def _analyze_asset(code: str, label: str, df: pd.DataFrame) -> dict | None:
    """分析单个标的在最近一根 K 线（日/周）的走势。"""
    if df is None or df.empty or len(df) < 20:
        return None

    last = df.iloc[-1]
    close = float(last.get("close") or 0)
    if close <= 0:
        return None

    prev_close = float(df.iloc[-2].get("close") or 0)
    change = (close - prev_close) / prev_close * 100 if prev_close > 0 else 0.0

    # 5 日（或 5 周）累计涨跌，用于判断短期动能
    base_close = float(df.iloc[-6].get("close") or 0) if len(df) >= 6 else prev_close
    change_5 = (close - base_close) / base_close * 100 if base_close > 0 else 0.0

    ma20 = last.get("ma20")
    ma60 = last.get("ma60")
    ema20 = last.get("ema20")
    ema30 = last.get("ema30")

    if pd.notna(ma20) and pd.notna(ma60):
        # 日线：MA20 vs MA60
        trend = "多头" if ma20 > ma60 else "空头"
    elif pd.notna(ema20) and pd.notna(ema30):
        # 周线（无 MA 列）：EMA20 vs EMA30
        trend = "多头" if ema20 > ema30 else "空头"
    elif pd.notna(ema20):
        trend = "多头" if close > ema20 else "空头"
    else:
        trend = "震荡"

    rsi = last.get("rsi6")
    rsi = float(rsi) if pd.notna(rsi) else None

    # 距 52 周（或 52 根）高点回撤
    high = float(df["high"].max())
    drawdown = (high - close) / high * 100 if high > 0 else 0.0

    return {
        "code": code,
        "label": label,
        "date": str(last.get("date", "")),
        "close": round(close, 2),
        "change_pct": round(change, 2),
        "change_5_pct": round(change_5, 2),
        "trend": trend,
        "rsi": round(rsi, 1) if rsi is not None else None,
        "drawdown_pct": round(drawdown, 1),
    }


def _change_desc(change: float) -> str:
    if change >= 2:
        return f"大涨 {change:+.2f}%"
    if change >= 0.5:
        return f"上涨 {change:+.2f}%"
    if change > -0.5:
        return f"持平 {change:+.2f}%"
    if change > -2:
        return f"下跌 {change:+.2f}%"
    return f"大跌 {change:+.2f}%"


def _rsi_desc(rsi) -> str:
    if rsi is None:
        return ""
    if rsi < 30:
        return "，RSI 超卖"
    if rsi > 70:
        return "，RSI 超买"
    return f"，RSI {rsi}"


def _asset_line(a: dict, period_label: str) -> str:
    """单标的一行点评（从模板渲染）。"""
    trend_icon = "↑" if a["trend"] == "多头" else ("↓" if a["trend"] == "空头" else "→")
    data = {
        "label": a["label"],
        "ticker": a["code"].split(".")[-1],
        "period_label": period_label,
        "change_desc": _change_desc(a["change_pct"]),
        "close": a["close"],
        "trend": a["trend"],
        "trend_icon": trend_icon,
        "rsi_desc": _rsi_desc(a["rsi"]),
        "drawdown_desc": f"，距高点回撤 {a['drawdown_pct']}%" if a["drawdown_pct"] >= 5 else "",
    }
    tpl = template_store.get_template("review_asset_line")
    return template_store.render(tpl["body"], data)


def _pick_line(p: dict) -> str:
    """交易机会一行。"""
    ticker = p["code"].split(".")[-1]
    return f"- **{ticker}**：评分 {p['score']}，折价 {p['discount_pct']}%，{p['signal']}。{p.get('trade_hint', '')}"


# ── 报告组装 ──────────────────────────────────────────────────────────────────


def _build_markdown(ktype: str, date: str, macro: list[dict], mag7: list[dict], picks: list[dict]) -> str:
    """组装 Markdown 复盘正文（从模板渲染）。"""
    period_word = "周" if ktype == "1w" else "日"
    period_label = "本周" if ktype == "1w" else "当日"

    macro_section = "\n".join(_asset_line(a, period_label) for a in macro)
    mag7_section = "\n".join(_asset_line(a, period_label) for a in mag7)
    picks_section = "\n".join(_pick_line(p) for p in picks) if picks else "今日无符合条件的低估做多机会。"

    data = {
        "period_word": period_word,
        "date": date,
        "macro_section": macro_section,
        "mag7_section": mag7_section,
        "picks_section": picks_section,
    }
    tpl = template_store.get_template("review_skeleton")
    return template_store.render(tpl["body"], data)


def generate_review(ktype: str = "1d", picks: list[dict] | None = None) -> dict:
    """生成复盘报告。

    Args:
        ktype: "1d" 日复盘 / "1w" 周复盘
        picks: 交易机会列表（daily-picks 的 picks），可为空

    Returns:
        {"type", "date", "title", "body", "macro", "mag7"}
    """
    macro = []
    mag7 = []
    date = ""

    for asset in REVIEW_ASSETS:
        df = storage.query_recent(asset["code"], ktype, limit=60)
        result = _analyze_asset(asset["code"], asset["label"], df)
        if result is None:
            continue
        if not date:
            date = result["date"]
        if asset["group"] == "macro":
            macro.append(result)
        else:
            mag7.append(result)

    period_word = "周" if ktype == "1w" else "日"
    body = _build_markdown(ktype, date, macro, mag7, picks or [])

    return {
        "type": ktype,
        "date": date,
        "title": f"市场{period_word}复盘（{date}）",
        "body": body,
        "macro": macro,
        "mag7": mag7,
    }
