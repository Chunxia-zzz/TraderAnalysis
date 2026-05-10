"""网格交易数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GridConfig:
    id: int
    code: str
    name: str
    status: str  # running / stopped / paused
    env: str  # simulate / live

    price_upper: float
    price_lower: float
    grid_count: int
    grid_spacing: float
    order_qty: int

    max_position: int
    daily_loss_limit: float
    max_orders_per_day: int

    trading_start: str  # "09:30"
    trading_end: str  # "15:50"


@dataclass
class GridState:
    config_id: int
    current_position: int = 0
    cost_basis: float = 0.0
    daily_pnl: float = 0.0
    daily_trades: int = 0
    last_price: float | None = None
    grid_status: dict[str, str] = field(default_factory=dict)  # {"0":"bought","1":"empty",...}


@dataclass
class Signal:
    direction: str  # BUY / SELL
    grid_level: int
    grid_price: float
