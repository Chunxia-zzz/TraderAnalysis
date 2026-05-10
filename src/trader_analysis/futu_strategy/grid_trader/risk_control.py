"""网格交易风控模块。"""

from __future__ import annotations

from datetime import datetime

import pytz

from trader_analysis.futu_strategy.grid_trader.models import GridConfig, GridState

ET = pytz.timezone("US/Eastern")


def is_trading_hours(cfg: GridConfig) -> bool:
    """判断当前是否在交易时段内（美东时间）。"""
    now_et = datetime.now(ET)

    # 周末不交易
    if now_et.weekday() >= 5:
        return False

    current_time = now_et.strftime("%H:%M")
    return cfg.trading_start <= current_time <= cfg.trading_end


def check_risk(state: GridState, cfg: GridConfig, direction: str) -> tuple[bool, str]:
    """风控检查。返回 (通过, 原因)。

    检查项：
    1. 买入时仓位不超限
    2. 单日亏损未熔断
    3. 单日交易次数未超限
    """
    # 最大仓位
    if direction == "BUY" and state.current_position >= cfg.max_position:
        return False, f"position limit reached ({state.current_position}/{cfg.max_position})"

    # 单日亏损熔断
    if state.daily_pnl <= cfg.daily_loss_limit:
        return False, f"daily loss limit triggered (${state.daily_pnl:.2f} <= ${cfg.daily_loss_limit:.2f})"

    # 单日交易次数
    if state.daily_trades >= cfg.max_orders_per_day:
        return False, f"max daily orders reached ({state.daily_trades}/{cfg.max_orders_per_day})"

    return True, ""
