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
        if "subgroups" in g and g["subgroups"]:
            # 子类结构：所有子类 items 总和 = 组权重
            g_items = [i for sg in g["subgroups"] for i in sg.get("items", [])]
            sg_sum = sum(float(sg.get("weight", 0)) for sg in g["subgroups"])
            if abs(sg_sum - float(g.get("weight", 0))) > 0.5:
                raise ValueError(f"分组 {g['label']} 子类权重 {sg_sum} ≠ 组权重 {g.get('weight')}")
        else:
            g_items = g.get("items", [])
        g_total = sum(float(i.get("weight", 0)) for i in g_items)
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
    """结合评分/RSI/折价生成加仓建议。

    规则：
    - 高于晨星公允价值 → "回调再买"（expensive）
    - 低于公允价值 + 评分高/RSI低 → "建议加仓"（buy）
    - 有差距但未到时机 → "等回调"（watch）
    - 已达标/超配 → hold
    """
    score = None
    rsi = None
    ms = None
    close = None
    try:
        conn = storage._get_conn()
        s = conn.execute(
            "SELECT total_score FROM score_results WHERE code = ? ORDER BY date DESC LIMIT 1", (code,)
        ).fetchone()
        row = conn.execute(
            "SELECT rsi6, close FROM kline_indicators WHERE code = ? AND ktype='1d' ORDER BY date DESC LIMIT 1", (code,)
        ).fetchone()
        w = conn.execute(
            "SELECT morningstar_fair_value FROM watchlist WHERE code = ?", (code,)
        ).fetchone()
        conn.close()
        score = float(s["total_score"]) if s else None
        rsi = float(row["rsi6"]) if row and row["rsi6"] is not None else None
        close = float(row["close"]) if row and row["close"] else None
        ms = float(w["morningstar_fair_value"]) if w and w["morningstar_fair_value"] else None
    except Exception:
        pass

    if gap <= 0:
        return {"score": score, "rsi": rsi, "action": "已达标或超配", "level": "hold", "reasons": []}

    # 规则：价格高于晨星公允价值 → 回调再买
    if ms and close and close > ms:
        premium = (close - ms) / ms * 100
        return {
            "score": score, "rsi": rsi,
            "action": f"高于公允价值 {premium:.0f}%，回调再买",
            "level": "expensive",
            "reasons": [f"溢价{premium:.0f}%"],
        }

    # 规则：评分≥80 且 低于公允价值（低估）→ 强烈建议加仓（超卖+低估）
    if ms and close and close < ms and score is not None and score >= 80:
        discount = (ms - close) / close * 100
        return {
            "score": score, "rsi": rsi,
            "action": f"强烈建议加仓（评分{score:.0f} + 低估{discount:.0f}%）",
            "level": "strong_buy",
            "reasons": [f"评分{score:.0f}高", f"低估{discount:.0f}%"],
        }

    reasons = []
    if score is not None and score >= 75:
        reasons.append(f"评分{score:.0f}高")
    if rsi is not None and rsi < 40:
        reasons.append(f"RSI超卖({rsi:.0f})")
    if ms and close:
        discount = (ms - close) / close * 100
        if discount > 10:
            reasons.append(f"低估{discount:.0f}%")

    if reasons:
        return {"score": score, "rsi": rsi, "action": "建议加仓", "level": "buy", "reasons": reasons}
    return {"score": score, "rsi": rsi, "action": "有差距，等回调", "level": "watch", "reasons": []}


# ── 分批加仓计划 ──────────────────────────────────────────────────────────────

_REF_ETF = {"gold": "US.GLD", "btc": "US.IBIT"}


def _spot_from_etf(group: dict, etf_price: float) -> float:
    """两点线性校准：把 ETF 价换算成现货/期货价。

    校准点：ETF1→现货1、ETF2→现货2（存于配置 calib_etf1/fut1/etf2/fut2）。
    """
    e1 = float(group["calib_etf1"])
    f1 = float(group["calib_fut1"])
    e2 = float(group["calib_etf2"])
    f2 = float(group["calib_fut2"])
    if e2 == e1:
        return etf_price * f1 / e1
    return f1 + (etf_price - e1) * (f2 - f1) / (e2 - e1)


def _batch_plan(group: dict, current_spot: float, gap_amount: float) -> dict:
    """按现货价格区间生成分批加仓计划（分 3 批）。

    批1（底部区 0~33%）买 50%、批2（中部 33~66%）买 30%、批3（顶部区 66~100%）买 20%。
    当前价 ≤ 某批顶部 → 该批可执行。价格越接近底部，可买批次越多。
    """
    bottom = float(group["short_bottom"])
    top = float(group["short_top"])
    if top <= bottom:
        return {"error": "区间无效（顶部需>底部）"}

    span = top - bottom
    tiers = [
        {"tier": 1, "low": bottom, "high": bottom + span * 0.33, "pct": 0.50},
        {"tier": 2, "low": bottom + span * 0.33, "high": bottom + span * 0.66, "pct": 0.30},
        {"tier": 3, "low": bottom + span * 0.66, "high": top, "pct": 0.20},
    ]
    p = (current_spot - bottom) / span
    exec_total = 0.0
    plan_tiers = []
    for t in tiers:
        executable = current_spot <= t["high"]
        if executable:
            exec_total += t["pct"]
        plan_tiers.append({
            "tier": t["tier"],
            "price_range": f"{t['low']:.0f}~{t['high']:.0f}",
            "pct": round(t["pct"] * 100),
            "amount": round(gap_amount * t["pct"], 0),
            "executable": executable,
        })

    return {
        "current_spot": round(current_spot, 0),
        "bottom": bottom,
        "top": top,
        "position_pct": round(max(0.0, min(1.0, p)) * 100),
        "exec_amount": round(gap_amount * exec_total, 0),
        "exec_pct": round(exec_total * 100),
        "tiers": plan_tiers,
    }


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

        def _build_items(raw_items):
            out = []
            for item in raw_items:
                code = item["code"]
                w = float(item.get("weight", 0))
                target_value = total_assets * w / 100
                pos = pos_map.get(code)
                actual_value = float(pos["market_value"]) if pos else 0.0
                gap = target_value - actual_value
                advice = _make_advice(code, gap)
                out.append({
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
            return out

        # 支持 subgroups（美股分大科技/半导体/灵活板块）
        subgroups = []
        has_subgroups = bool(g.get("subgroups"))
        if has_subgroups:
            for sg in g["subgroups"]:
                sg_items = _build_items(sg.get("items", []))
                sg_actual = sum(i["actual_value"] for i in sg_items)
                subgroups.append({
                    "label": sg["label"],
                    "weight": float(sg.get("weight", 0)),
                    "target_value": round(total_assets * float(sg.get("weight", 0)) / 100, 2),
                    "actual_value": round(sg_actual, 2),
                    "items": sg_items,
                })
            items = [i for sg in subgroups for i in sg["items"]]
        else:
            items = _build_items(g.get("items", []))

        g_actual = sum(i["actual_value"] for i in items)

        # 分批加仓计划（黄金/比特币有现货区间时）
        batch_plan = None
        if g.get("short_bottom") and g.get("calib_etf1"):
            ref_etf = _REF_ETF.get(g["key"])
            ref_price = None
            pos = pos_map.get(ref_etf) if ref_etf else None
            if pos and pos.get("price"):
                ref_price = float(pos["price"])
            else:
                try:
                    conn3 = storage._get_conn()
                    c3 = conn3.execute(
                        "SELECT close FROM kline_indicators WHERE code = ? AND ktype='1d' ORDER BY date DESC LIMIT 1",
                        (ref_etf,),
                    ).fetchone()
                    conn3.close()
                    if c3 and c3["close"]:
                        ref_price = float(c3["close"])
                except Exception:
                    pass
            if ref_price:
                current_spot = _spot_from_etf(g, ref_price)
                batch_plan = _batch_plan(g, current_spot, g_target_value - g_actual)

        groups_out.append({
            "key": g["key"],
            "label": g["label"],
            "weight": g_weight,
            "target_value": round(g_target_value, 2),
            "actual_value": round(g_actual, 2),
            "gap": round(g_target_value - g_actual, 2),
            "items": items,
            **({"subgroups": subgroups} if has_subgroups else {}),
            **({"batch_plan": batch_plan} if batch_plan else {}),
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
