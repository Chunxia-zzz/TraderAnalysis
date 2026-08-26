"""实盘/模拟盘持仓查询与配比计算。

依赖富途 OpenD（127.0.0.1:11111），每次调用实时刷新：
- accinfo_query  → 账户现金/总资产/持仓市值
- position_list_query(refresh_cache=True) → 持仓明细（最新市价）

配比 = 每只持仓市值 ÷ 总资产。账户总资产以 HKD 记账，
美股持仓（USD）按近似汇率换算到 HKD 统一口径。
"""

from __future__ import annotations

import logging

from trader_analysis.futu_strategy import config

logger = logging.getLogger(__name__)

# USD → HKD 近似汇率（用于统一市值口径；账户基础货币为 HKD 时使用）
USD_HKD_RATE = 7.8
# 其他币种 → HKD 近似汇率
_CURRENCY_RATE = {
    "HKD": 1.0,
    "USD": USD_HKD_RATE,
    "CNH": 1.1,
    "JPY": 0.055,
}


def fetch_position(env: str = "REAL") -> dict:
    """获取账户资产 + 持仓 + 配比（实时刷新）。

    Args:
        env: "REAL" 实盘 / "SIMULATE" 模拟盘

    Returns:
        dict: 账户摘要 + positions 列表；OpenD 不可用或失败时返回 {"error": ...}
    """
    try:
        from futu import OpenSecTradeContext, RET_OK, SecurityFirm, TrdEnv  # type: ignore[import]
    except ImportError as exc:
        return {"error": "futu-api 未安装，请执行: pip install futu-api"}

    try:
        trd = OpenSecTradeContext(
            host=config.OPEND_HOST,
            port=config.OPEND_PORT,
            security_firm=SecurityFirm.FUTUSECURITIES,
        )
    except Exception as exc:
        logger.error(f"连接 OpenD 失败: {exc}")
        return {"error": f"连接富途 OpenD 失败：{exc}"}

    try:
        # ── 1. 定位账户 ──
        ret, accs = trd.get_acc_list()
        if ret != RET_OK:
            return {"error": f"获取账户列表失败: {accs}"}
        targets = accs[accs["trd_env"] == env]
        if targets.empty:
            return {"error": f"未找到 {env} 账户（可用: {accs['trd_env'].unique().tolist()}）"}
        acc_id = int(targets.iloc[0]["acc_id"])

        trd_env = TrdEnv.REAL if env == "REAL" else TrdEnv.SIMULATE

        # ── 2. 账户资金 ──
        ret, info = trd.accinfo_query(trd_env=trd_env, acc_id=acc_id)
        if ret != RET_OK:
            return {"error": f"获取账户资金失败: {info}"}
        r = info.iloc[0]
        cash = float(r.get("cash") or 0)
        total_assets = float(r.get("total_assets") or 0)
        market_val = float(r.get("market_val") or 0)
        base_currency = r.get("currency") or "HKD"

        # ── 3. 持仓明细（实时刷新市价）──
        ret, pos = trd.position_list_query(trd_env=trd_env, acc_id=acc_id, refresh_cache=True)
        if ret != RET_OK:
            return {"error": f"获取持仓失败: {pos}"}

        positions = []
        for _, p in pos.iterrows():
            currency = p.get("currency") or "USD"
            rate = _CURRENCY_RATE.get(currency, USD_HKD_RATE)
            mv = float(p.get("market_val") or 0)
            mv_hkd = mv * rate
            weight = mv_hkd / total_assets * 100 if total_assets else 0.0
            positions.append({
                "code": p.get("code"),
                "name": p.get("stock_name") or "",
                "qty": float(p.get("qty") or 0),
                "cost_price": round(float(p.get("cost_price") or 0), 4),
                "price": round(float(p.get("nominal_price") or 0), 4),
                "market_value": round(mv, 2),
                "market_value_hkd": round(mv_hkd, 2),
                "currency": currency,
                "weight_pct": round(weight, 2),
                "pl_pct": round(float(p.get("pl_ratio") or 0), 2),
            })

        # 按市值（HKD）降序
        positions.sort(key=lambda x: -abs(x["market_value_hkd"]))

        return {
            "env": env,
            "acc_id": acc_id,
            "base_currency": base_currency,
            "usd_hkd_rate": USD_HKD_RATE,
            "cash": round(cash, 2),
            "total_assets": round(total_assets, 2),
            "market_value": round(market_val, 2),
            "cash_pct": round(cash / total_assets * 100, 1) if total_assets else 0.0,
            "position_pct": round(market_val / total_assets * 100, 1) if total_assets else 0.0,
            "position_count": len(positions),
            "positions": positions,
            "timestamp": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as exc:
        logger.exception(f"查询持仓异常: {exc}")
        return {"error": f"查询持仓失败：{exc}"}
    finally:
        try:
            trd.close()
        except Exception:
            pass
