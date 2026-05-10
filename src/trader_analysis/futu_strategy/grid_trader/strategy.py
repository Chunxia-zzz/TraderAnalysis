"""网格策略逻辑：网格线计算 + 信号判断 + 动作决策。"""

from __future__ import annotations

from trader_analysis.futu_strategy.grid_trader.models import GridConfig, Signal


def calculate_grid_lines(cfg: GridConfig) -> list[float]:
    """生成等间距网格线列表（从低到高）。

    例: upper=250, lower=240, grid_count=5
    间距 = 2.0, 网格线 = [240, 242, 244, 246, 248, 250]
    """
    spacing = (cfg.price_upper - cfg.price_lower) / cfg.grid_count
    return [round(cfg.price_lower + i * spacing, 4) for i in range(cfg.grid_count + 1)]


def detect_crossing(price: float, prev_price: float, grid_lines: list[float]) -> Signal | None:
    """判断价格是否穿越网格线。

    - 下穿（prev >= line, price < line）→ BUY
    - 上穿（prev <= line, price > line）→ SELL
    - 只返回最近穿越的一条（防止跳空连锁）
    """
    best_signal: Signal | None = None
    best_dist = float("inf")

    for i, line in enumerate(grid_lines):
        # 下穿: BUY
        if prev_price >= line > price:
            dist = abs(price - line)
            if dist < best_dist:
                best_dist = dist
                best_signal = Signal(direction="BUY", grid_level=i, grid_price=line)
        # 上穿: SELL
        elif prev_price <= line < price:
            dist = abs(price - line)
            if dist < best_dist:
                best_dist = dist
                best_signal = Signal(direction="SELL", grid_level=i, grid_price=line)

    return best_signal


def should_execute(signal: Signal, grid_status: dict[str, str]) -> bool:
    """结合网格状态决定是否执行。

    - BUY + empty → 执行
    - BUY + bought → 跳过
    - SELL + bought → 执行
    - SELL + empty → 跳过
    """
    level_key = str(signal.grid_level)
    current_state = grid_status.get(level_key, "empty")

    if signal.direction == "BUY" and current_state == "empty":
        return True
    if signal.direction == "SELL" and current_state == "bought":
        return True
    return False
