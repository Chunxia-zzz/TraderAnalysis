"""目标仓位（永久投资组合）规划与对比。

三大类资产：美股 / 黄金 / 比特币，各自内部可选标的。
- 目标配置存 JSON（data/target_allocation.json），页面可编辑
- 实时对比富途持仓（复用 position_fetcher，USD 口径）
- 每只标的：目标市值 vs 实际市值 → 差距（加仓金额）
- 加仓建议结合：评分（基本面）+ RSI（情绪）+ 晨星折价（估值）
"""

from __future__ import annotations

import json
import logging
import os

from trader_analysis.futu_strategy import config, storage
from trader_analysis.futu_strategy.position_fetcher import fetch_position

logger = logging.getLogger(__name__)

ALLOCATION_PATH = os.path.join(os.path.dirname(config.DB_PATH), "target_allocation.json")


# ── 默认目标配置（初始模板，页面可改）──────────────────────────────────────────

DEFAULT_ALLOCATION: dict = {
    "note": "永久投资组合：美股+黄金+比特币。权重总和=100%，页面可调整。",
    "groups": [
        {
            "key": "stock",
            "label": "美股",
            "weight": 60,
            "items": [
                {"code": "US.NVDA", "weight": 8},
                {"code": "US.MSFT", "weight": 7},
                {"code": "US.AAPL", "weight": 7},
                {"code": "US.AMZN", "weight": 6},
                {"code": "US.GOOGL", "weight": 6},
                {"code": "US.META", "weight": 5},
                {"code": "US.TSLA", "weight": 5},
                {"code": "US.AVGO", "weight": 5},
                {"code": "US.TSM", "weight": 4},
                {"code": "US.ASML", "weight": 4},
                {"code": "US.INTC", "weight": 3},
            ],
        },
        {
            "key": "gold",
            "label": "黄金",
            "weight": 20,
            "items": [
                {"code": "US.GLD", "weight": 12},
                {"code": "US.GDX", "weight": 8},
            ],
        },
        {
            "key": "btc",
            "label": "比特币",
            "weight": 20,
            "items": [
                {"code": "US.IBIT", "weight": 10},
                {"code": "US.MSTR", "weight": 6},
                {"code": "US.CRCL", "weight": 4},
            ],
        },
    ],
}


# ── 配置读写 ──────────────────────────────────────────────────────────────────


def load_allocation() -> dict:
    """读目标配置，文件不存在或损坏时回退默认。"""
    if os.path.exists(ALLOCATION_PATH):
        try:
            with open(ALLOCATION_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning(f"读取目标配置失败，使用默认: {exc}")
    return json.loads(json.dumps(DEFAULT_ALLOCATION))


def save_allocation(config_data: dict) -> dict:
    """保存目标配置（校验权重总和=100）。"""
    total = 0
    for g in config_data.get("groups", []):
        g_total = sum(float(i.get("weight", 0)) for i in g.get("items", []))
        if abs(g_total - float(g.get("weight", 0))) > 0.5:
            raise ValueError(f"分组 {g['label']} 内部权重 {g_total} ≠ 组权重 {g.get('weight')}")
        total += float(g.get("weight", 0))
    if abs(total - 100) > 0.5:
        raise ValueError(f"各组权重总和 {total} ≠ 100")

    os.makedirs(os.path.dirname(ALLOCATION_PATH), exist_ok=True)
    with open(ALLOCATION_PATH, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=2)
    return config_data


# ── 加仓建议 ──────────────────────────────────────────────────────────────────


def _make_advice(code: str, gap: float) -> dict:
    """结合评分/RSI/折价生成加仓建议。"""
    # 最新评分
    score = None
    try:
        conn = storage._get_conn()
        s = conn.execute(
            "SELECT total_score FROM score_results WHERE code = ? ORDER BY date DESC LIMIT 1", (code,)
        ).fetchone()
        rsi_row = conn.execute(
            "SELECT rsi6 FROM kline_indicators WHERE code = ? AND ktype='1d' ORDER BY date DESC LIMIT 1", (code,)
        ).fetchone()
        w = conn.execute(
            "SELECT morningstar_fair_value FROM watchlist WHERE code = ?", (code,)
        ).fetchone()
        conn.close()
        score = float(s["total_score"]) if s else None
        rsi = float(rsi_row["rsi6"]) if rsi_row and rsi_row["rsi6"] is not None else None
        ms = float(w["morningstar_fair_value"]) if w and w["morningstar_fair_value"] else None
    except Exception:
        rsi, ms = None, None

    if gap <= 0:
        return {"score": score, "rsi": rsi, "action": "已达标或超配", "level": "hold", "reasons": []}

    reasons = []
    if score is not None and score >= 75:
        reasons.append(f"评分{score:.0f}高")
    if rsi is not None and rsi < 40:
        reasons.append(f"RSI超卖({rsi:.0f})")
    if ms:
        discount = None
        try:
            # 从持仓拿不到现价，用最新收盘价算折价
            conn2 = storage._get_conn()
            c = conn2.execute(
                "SELECT close FROM kline_indicators WHERE code = ? AND ktype='1d' ORDER BY date DESC LIMIT 1", (code,)
            ).fetchone()
            conn2.close()
            if c and c["close"]:
                discount = (ms - float(c["close"])) / float(c["close"]) * 100
        except Exception:
            pass
        if discount and discount > 10:
            reasons.append(f"低估{discount:.0f}%")

    if reasons:
        return {"score": score, "rsi": rsi, "action": "建议加仓", "level": "buy", "reasons": reasons}
    return {"score": score, "rsi": rsi, "action": "有差距，等回调", "level": "watch", "reasons": []}


# ── 主计算 ────────────────────────────────────────────────────────────────────


def compute_allocation(env: str = "REAL") -> dict:
    """计算目标仓位 vs 实际持仓对比。"""
    config_data = load_allocation()

    # 实时持仓（USD 口径，与目标市值一致）
    pos_result = fetch_position(env=env, display_currency="USD")
    if "error" in pos_result:
        return {"error": pos_result["error"]}

    total_assets = pos_result["total_assets"]
    pos_map = {p["code"]: p for p in pos_result["positions"]}

    groups_out = []
    all_items = []
    for g in config_data.get("groups", []):
        g_weight = float(g.get("weight", 0))
        g_target_value = total_assets * g_weight / 100

        items = []
        g_actual = 0.0
        for item in g.get("items", []):
            code = item["code"]
            w = float(item.get("weight", 0))
            target_value = total_assets * w / 100
            pos = pos_map.get(code)
            actual_value = float(pos["market_value"]) if pos else 0.0
            gap = target_value - actual_value
            g_actual += actual_value

            advice = _make_advice(code, gap)
            items.append({
                "code": code,
                "name": pos["name"] if pos else "",
                "weight": w,
                "target_value": round(target_value, 2),
                "actual_value": round(actual_value, 2),
                "gap": round(gap, 2),
                "qty": pos["qty"] if pos else 0,
                "price": pos["price"] if pos else None,
                "pl_pct": pos["pl_pct"] if pos else None,
                **advice,
            })

        groups_out.append({
            "key": g["key"],
            "label": g["label"],
            "weight": g_weight,
            "target_value": round(g_target_value, 2),
            "actual_value": round(g_actual, 2),
            "gap": round(g_target_value - g_actual, 2),
            "items": items,
        })
        all_items.extend(items)

    # 加仓优先级：有差距且建议买入的排前面，按差距金额降序
    buy_items = [i for i in all_items if i["gap"] > 0]
    buy_items.sort(key=lambda x: (-x["gap"]))

    return {
        "env": env,
        "currency": "USD",
        "total_assets": round(total_assets, 2),
        "groups": groups_out,
        "buy_priority": buy_items,
        "note": config_data.get("note", ""),
        "timestamp": pos_result.get("timestamp", ""),
    }
