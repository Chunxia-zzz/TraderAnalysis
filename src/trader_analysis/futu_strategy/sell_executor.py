"""模拟盘卖出执行。

接收 SellAction 指令，通过富途 API 执行卖出，更新持仓状态，写交易日志。
"""

from __future__ import annotations

import logging
from datetime import date

from trader_analysis.futu_strategy import storage
from trader_analysis.futu_strategy.logger import log_trade
from trader_analysis.futu_strategy.sell_advisor import SellAction

logger = logging.getLogger(__name__)


def execute_sell(
    action: SellAction,
    acc_id: int,
    trd_ctx,
    quote_ctx,
) -> None:
    """执行卖出操作。

    流程：
    1. 获取当前快照价格
    2. 下限价卖出单（模拟盘）
    3. 更新 position_state 表
    4. 写交易日志

    Parameters
    ----------
    action    : SellAction 操作指令
    acc_id    : 模拟账户 ID
    trd_ctx   : OpenSecTradeContext 实例（全程复用，不在此创建/关闭）
    quote_ctx : OpenQuoteContext 实例（用于获取当前快照价格）
    """
    try:
        from futu import OrderType, TrdEnv, TrdSide  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError("futu-api 未安装，请执行: pip install futu-api") from exc

    if action.action != "SELL" or action.sell_qty <= 0:
        return

    code = action.code

    # 1. 获取当前快照价格
    ret, df = quote_ctx.get_market_snapshot([code])
    if ret != 0:
        logger.error(f"获取 {code} 快照失败: {df}")
        return
    current_price = float(df["last_price"].iloc[0])
    if current_price <= 0:
        logger.warning(f"{code} 快照价格异常: {current_price}，跳过卖出")
        return

    # 2. 下单（模拟盘限价卖出单）
    ret2, order_data = trd_ctx.place_order(
        price=current_price,
        qty=action.sell_qty,
        code=code,
        trd_side=TrdSide.SELL,
        order_type=OrderType.NORMAL,
        trd_env=TrdEnv.SIMULATE,
        acc_id=acc_id,
    )

    today = date.today().isoformat()

    if ret2 == 0:
        order_id = str(order_data.get("order_id", ""))
        status = "success"
        logger.info(
            f"[SELL] {code} 卖出成功: qty={action.sell_qty}, price={current_price:.2f}, "
            f"stage={action.new_stage}, reason={action.reason}, order_id={order_id}"
        )
    else:
        order_id = ""
        status = "failed"
        logger.error(f"[SELL] {code} 卖出失败: {order_data}")

    # 3. 更新持仓状态
    existing = storage.get_position_state(code)
    new_remaining = existing.get("remaining_qty", 0) - action.sell_qty
    new_remaining = max(new_remaining, 0)

    storage.upsert_position_state(
        code=code,
        stage=action.new_stage,
        remaining_qty=new_remaining,
        last_signal=",".join(action.signals),
        last_signal_date=today,
    )

    # 4. 写交易日志
    log_trade({
        "code": code,
        "signal": f"SELL_{action.new_stage}",
        "score": 0,
        "qty": action.sell_qty,
        "price": current_price,
        "order_id": order_id,
        "trd_env": "SIMULATE",
        "status": status,
        "reason": action.reason,
        "stage": action.new_stage,
        "triggered_signals": action.signals,
    })
