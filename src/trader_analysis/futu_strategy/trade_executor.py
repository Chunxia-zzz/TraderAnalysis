"""模拟盘交易执行。

根据评分结果下单：
  STRONG_BUY → 按 config.POSITION_CONFIG["STRONG_BUY"]["amount_usd"] 买入
  BUY        → 按 config.POSITION_CONFIG["BUY"]["amount_usd"] 买入
  NO_ACTION  → 不操作
"""

from __future__ import annotations

import logging

from trader_analysis.futu_strategy import config
from trader_analysis.futu_strategy.logger import log_trade

logger = logging.getLogger(__name__)


def execute_trade(
    signal: dict,
    acc_id: int,
    trd_ctx,
    quote_ctx,
) -> None:
    """执行一次交易。

    Parameters
    ----------
    signal:    scorer.calculate_score() 的返回值
    acc_id:    模拟账户 ID（运行开始时一次性获取，全程复用）
    trd_ctx:   OpenSecTradeContext 实例（全程复用，不在此处创建/关闭）
    quote_ctx: OpenQuoteContext 实例（用于获取当前快照价格）
    """
    try:
        from futu import OrderType, TrdEnv, TrdSide  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError("futu-api 未安装，请执行: pip install futu-api") from exc

    sig = signal.get("signal", "NO_ACTION")
    if sig == "NO_ACTION":
        return

    code = signal["code"]

    # 1. 获取当前快照价格
    ret, df = quote_ctx.get_market_snapshot([code])
    if ret != 0:
        logger.error(f"获取 {code} 快照失败: {df}")
        return
    current_price = float(df["last_price"].iloc[0])
    if current_price <= 0:
        logger.warning(f"{code} 快照价格异常: {current_price}，跳过")
        return

    # 2. 计算买入数量
    amount_usd = config.POSITION_CONFIG[sig]["amount_usd"]
    qty = int(amount_usd / current_price)
    if qty <= 0:
        logger.warning(f"{code} 计算数量为 0（价格 {current_price}，金额 {amount_usd}），跳过")
        return

    # 3. 检查持仓（避免重复买入，除非开启加仓）
    if not config.ALLOW_PYRAMID:
        ret2, pos_df = trd_ctx.position_list_query(code=code, refresh_cache=True)
        if ret2 == 0 and not pos_df.empty and pos_df["qty"].sum() > 0:
            logger.info(f"{code} 已持有 {pos_df['qty'].sum()} 股，跳过买入（ALLOW_PYRAMID=False）")
            return

    # 4. 下单（模拟盘限价单）
    ret3, order_data = trd_ctx.place_order(
        price=current_price,
        qty=qty,
        code=code,
        trd_side=TrdSide.BUY,
        order_type=OrderType.NORMAL,
        trd_env=TrdEnv.SIMULATE,
        acc_id=acc_id,
    )

    if ret3 == 0:
        order_id = str(order_data.get("order_id", ""))
        status = "success"
        logger.info(
            f"[{sig}] {code} 下单成功：qty={qty}, price={current_price}, order_id={order_id}"
        )
    else:
        order_id = ""
        status = "failed"
        logger.error(f"[{sig}] {code} 下单失败: {order_data}")

    # 5. 写交易日志
    log_trade({
        "code": code,
        "signal": sig,
        "score": signal.get("total_score", 0),
        "qty": qty,
        "price": current_price,
        "order_id": order_id,
        "trd_env": "SIMULATE",
        "status": status,
    })
