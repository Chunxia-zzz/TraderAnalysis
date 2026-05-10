"""富途下单封装。"""

from __future__ import annotations

import logging

logger = logging.getLogger("grid_trader")


def place_grid_order(trd_ctx, code: str, direction: str, qty: int, price: float, env: str) -> str | None:
    """下限价单，返回 order_id。失败返回 None。

    Args:
        trd_ctx: OpenSecTradeContext 实例
        code: 标的代码 (US.GLD)
        direction: "BUY" / "SELL"
        qty: 股数
        price: 限价
        env: "simulate" / "live"
    """
    try:
        from futu import OrderType, TrdEnv, TrdMarket, TrdSide
    except ImportError:
        logger.error("futu-api 未安装")
        return None

    trd_side = TrdSide.BUY if direction == "BUY" else TrdSide.SELL
    trd_env = TrdEnv.SIMULATE if env == "simulate" else TrdEnv.REAL

    ret, data = trd_ctx.place_order(
        price=price,
        qty=qty,
        code=code,
        trd_side=trd_side,
        order_type=OrderType.NORMAL,
        trd_env=trd_env,
        trd_market=TrdMarket.US,
    )

    if ret == 0:
        order_id = str(data.iloc[0]["order_id"])
        logger.info(f"[ORDER] {direction} {qty}@{price} order_id={order_id}")
        return order_id
    else:
        logger.error(f"[ORDER FAILED] {direction} {qty}@{price}: {data}")
        return None
