"""持仓阶段状态管理。

提供对 position_state 表的 CRUD 操作，供 sell_advisor 和 runner 调用。
"""

from __future__ import annotations

from trader_analysis.futu_strategy import storage


def get_state(code: str) -> dict:
    """查询单只标的的持仓状态。无记录时返回默认 HOLD 状态。"""
    return storage.get_position_state(code)


def update_state(
    code: str,
    new_stage: str,
    remaining_qty: int,
    signal: str,
    signal_date: str,
) -> None:
    """更新持仓阶段及最后信号信息。"""
    storage.upsert_position_state(
        code=code,
        stage=new_stage,
        remaining_qty=remaining_qty,
        last_signal=signal,
        last_signal_date=signal_date,
    )


def init_position(
    code: str,
    qty: int,
    avg_cost: float,
    entry_date: str,
) -> None:
    """买入成交后初始化持仓状态（由 trade_executor 在买入后调用）。"""
    storage.upsert_position_state(
        code=code,
        stage="HOLD",
        remaining_qty=qty,
        total_qty=qty,
        avg_cost=avg_cost,
        entry_date=entry_date,
    )


def list_active_positions() -> list[dict]:
    """列出所有非 EMPTY 的持仓。"""
    return storage.list_active_positions()


def reset_position(code: str) -> None:
    """清除持仓状态（手动重置用），将 stage 设为 EMPTY。"""
    storage.reset_position_state(code)
