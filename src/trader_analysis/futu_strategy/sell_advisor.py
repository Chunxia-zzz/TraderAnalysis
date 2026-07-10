"""减仓决策引擎。

读取持仓状态 + 当日信号列表，输出操作指令。
状态机核心逻辑：信号触发阶段推进，阶段决定减仓比例。

状态流转：
  HOLD ──(NEAR_HIGH + 背离信号)──► SELL_1 ──(BREAK_MA5)──► SELL_2
       ──(EMERGENCY_STOP)──────────────────────────────────► STOPPED_OUT
  SELL_2 ──(MA5_DEATH_CROSS / MA5_NO_RECOVERY)─────────────► SELL_3 / EMPTY
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from trader_analysis.futu_strategy import config
from trader_analysis.futu_strategy.top_detector import TopSignal


@dataclass
class SellAction:
    """减仓操作指令。"""
    code: str
    action: str            # "SELL" / "NO_ACTION"
    sell_qty: int          # 本次卖出数量（0 表示不操作）
    reason: str            # 触发原因描述
    new_stage: str         # 操作后的新阶段
    signals: list[str] = field(default_factory=list)  # 触发的信号类型列表


def evaluate(
    code: str,
    signals: list[TopSignal],
    current_stage: str,
    remaining_qty: int,
    total_qty: int,
) -> SellAction:
    """根据当日信号和当前阶段，决定是否减仓及数量。

    决策优先级（高→低）：
    1. EMERGENCY_STOP → 无论当前阶段，立即全部卖出（保留 keep_min_qty）
    2. 阶段推进逻辑（按 HOLD→SELL_1→SELL_2→SELL_3）

    Parameters
    ----------
    code           : 标的代码
    signals        : 当日触发的信号列表
    current_stage  : 当前持仓阶段
    remaining_qty  : 当前剩余股数
    total_qty      : 初始总股数（用于计算第一刀比例）

    Returns
    -------
    SellAction 操作指令
    """
    cfg = config.SELL_CONFIG
    keep_min = cfg.get("keep_min_qty", 1)
    signal_types = {s.signal_type for s in signals}

    no_action = SellAction(
        code=code, action="NO_ACTION", sell_qty=0,
        reason="", new_stage=current_stage, signals=list(signal_types),
    )

    if remaining_qty <= 0:
        return no_action

    # ── 优先级1：紧急止损，无视阶段 ─────────────────────────────────────────
    if "EMERGENCY_STOP" in signal_types:
        sell_qty = max(remaining_qty - keep_min, 0)
        return SellAction(
            code=code, action="SELL", sell_qty=sell_qty,
            reason="紧急止损",
            new_stage="STOPPED_OUT",
            signals=list(signal_types),
        )

    # ── 优先级2：按阶段推进 ──────────────────────────────────────────────────
    if current_stage == "HOLD":
        has_near_high = "NEAR_HIGH" in signal_types
        has_divergence = bool(signal_types & {"RSI_TOP_DIV", "VOLUME_STALL", "MACD_TOP_DIV"})

        if has_near_high and has_divergence:
            sell_qty = math.floor((total_qty if total_qty > 0 else remaining_qty) * cfg.get("sell_1_ratio", 1 / 3))
            sell_qty = min(sell_qty, remaining_qty)
            if sell_qty <= 0:
                return no_action
            return SellAction(
                code=code, action="SELL", sell_qty=sell_qty,
                reason="顶背离确认，减仓1/3",
                new_stage="SELL_1",
                signals=list(signal_types),
            )

    elif current_stage == "SELL_1":
        if "BREAK_MA5" in signal_types:
            sell_qty = math.floor(remaining_qty * cfg.get("sell_2_ratio", 2 / 3))
            sell_qty = min(sell_qty, remaining_qty - keep_min)
            sell_qty = max(sell_qty, 0)
            if sell_qty <= 0:
                return no_action
            return SellAction(
                code=code, action="SELL", sell_qty=sell_qty,
                reason="跌破MA5，减仓2/3",
                new_stage="SELL_2",
                signals=list(signal_types),
            )

    elif current_stage == "SELL_2":
        if "MA5_DEATH_CROSS" in signal_types or "MA5_NO_RECOVERY" in signal_types:
            sell_qty = max(remaining_qty - keep_min, 0)
            trigger = "MA5死叉" if "MA5_DEATH_CROSS" in signal_types else "连续未站回MA5"
            if sell_qty <= 0:
                return no_action
            new_stage = "EMPTY" if sell_qty >= remaining_qty - keep_min else "SELL_3"
            return SellAction(
                code=code, action="SELL", sell_qty=sell_qty,
                reason=f"{trigger}，清仓",
                new_stage=new_stage,
                signals=list(signal_types),
            )

    return no_action
