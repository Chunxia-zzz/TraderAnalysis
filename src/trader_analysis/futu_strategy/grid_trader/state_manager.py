"""网格交易状态管理 + DB 读写。"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime

from trader_analysis.futu_strategy import config
from trader_analysis.futu_strategy.grid_trader.models import GridConfig, GridState

_GRID_DDL = """
CREATE TABLE IF NOT EXISTS grid_config (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT NOT NULL,
    name            TEXT DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'stopped',
    env             TEXT NOT NULL DEFAULT 'simulate',
    price_upper     REAL NOT NULL,
    price_lower     REAL NOT NULL,
    grid_count      INTEGER NOT NULL,
    grid_spacing    REAL,
    order_qty       INTEGER NOT NULL,
    max_position    INTEGER NOT NULL,
    daily_loss_limit REAL DEFAULT -500.0,
    max_orders_per_day INTEGER DEFAULT 50,
    trading_start   TEXT DEFAULT '09:30',
    trading_end     TEXT DEFAULT '15:50',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS grid_orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id       INTEGER NOT NULL,
    code            TEXT NOT NULL,
    env             TEXT NOT NULL,
    direction       TEXT NOT NULL,
    grid_level      INTEGER NOT NULL,
    grid_price      REAL NOT NULL,
    order_qty       INTEGER NOT NULL,
    order_id        TEXT,
    fill_price      REAL,
    fill_qty        INTEGER,
    status          TEXT NOT NULL DEFAULT 'pending',
    pnl             REAL,
    triggered_at    TEXT NOT NULL,
    filled_at       TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_grid_orders_config ON grid_orders(config_id);
CREATE INDEX IF NOT EXISTS idx_grid_orders_time ON grid_orders(triggered_at);

CREATE TABLE IF NOT EXISTS grid_state (
    config_id       INTEGER PRIMARY KEY,
    current_position INTEGER DEFAULT 0,
    cost_basis      REAL DEFAULT 0.0,
    daily_pnl       REAL DEFAULT 0.0,
    daily_trades    INTEGER DEFAULT 0,
    last_price      REAL,
    last_update     TEXT,
    grid_status     TEXT DEFAULT '{}',
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_grid_tables() -> None:
    """建表（幂等）。"""
    conn = _get_conn()
    conn.executescript(_GRID_DDL)
    conn.close()


# ── Config CRUD ──────────────────────────────────────────────────────────────


def create_config(
    code: str,
    price_upper: float,
    price_lower: float,
    grid_count: int,
    order_qty: int,
    max_position: int,
    env: str = "simulate",
    name: str = "",
    daily_loss_limit: float = -500.0,
    max_orders_per_day: int = 50,
    trading_start: str = "09:30",
    trading_end: str = "15:50",
) -> int:
    """创建网格配置，返回 config_id。"""
    spacing = round((price_upper - price_lower) / grid_count, 4)
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO grid_config "
        "(code, name, env, price_upper, price_lower, grid_count, grid_spacing, order_qty, "
        "max_position, daily_loss_limit, max_orders_per_day, trading_start, trading_end) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (code, name, env, price_upper, price_lower, grid_count, spacing, order_qty,
         max_position, daily_loss_limit, max_orders_per_day, trading_start, trading_end),
    )
    config_id = cur.lastrowid
    # 初始化 grid_state
    conn.execute(
        "INSERT OR IGNORE INTO grid_state (config_id, grid_status) VALUES (?, ?)",
        (config_id, "{}"),
    )
    conn.commit()
    conn.close()
    return config_id


def get_config(config_id: int) -> GridConfig | None:
    """加载配置。"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM grid_config WHERE id = ?", (config_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return GridConfig(
        id=row["id"],
        code=row["code"],
        name=row["name"],
        status=row["status"],
        env=row["env"],
        price_upper=row["price_upper"],
        price_lower=row["price_lower"],
        grid_count=row["grid_count"],
        grid_spacing=row["grid_spacing"],
        order_qty=row["order_qty"],
        max_position=row["max_position"],
        daily_loss_limit=row["daily_loss_limit"],
        max_orders_per_day=row["max_orders_per_day"],
        trading_start=row["trading_start"],
        trading_end=row["trading_end"],
    )


def list_configs() -> list[dict]:
    """列出所有配置。"""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM grid_config ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_config_status(config_id: int, status: str) -> None:
    """更新配置状态 (running/stopped/paused)。"""
    conn = _get_conn()
    conn.execute(
        "UPDATE grid_config SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, config_id),
    )
    conn.commit()
    conn.close()


# ── State ────────────────────────────────────────────────────────────────────


def get_state(config_id: int) -> GridState:
    """加载运行时状态。"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM grid_state WHERE config_id = ?", (config_id,)).fetchone()
    conn.close()
    if not row:
        return GridState(config_id=config_id)
    return GridState(
        config_id=config_id,
        current_position=row["current_position"],
        cost_basis=row["cost_basis"],
        daily_pnl=row["daily_pnl"],
        daily_trades=row["daily_trades"],
        last_price=row["last_price"],
        grid_status=json.loads(row["grid_status"]) if row["grid_status"] else {},
    )


def save_state(state: GridState) -> None:
    """持久化状态。"""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO grid_state "
        "(config_id, current_position, cost_basis, daily_pnl, daily_trades, "
        "last_price, last_update, grid_status, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (
            state.config_id,
            state.current_position,
            state.cost_basis,
            state.daily_pnl,
            state.daily_trades,
            state.last_price,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            json.dumps(state.grid_status),
        ),
    )
    conn.commit()
    conn.close()


def daily_reset(config_id: int) -> None:
    """每日重置计数器。"""
    conn = _get_conn()
    conn.execute(
        "UPDATE grid_state SET daily_pnl = 0, daily_trades = 0, updated_at = datetime('now') "
        "WHERE config_id = ?",
        (config_id,),
    )
    conn.commit()
    conn.close()


# ── Orders ───────────────────────────────────────────────────────────────────


def insert_order(
    config_id: int,
    code: str,
    env: str,
    direction: str,
    grid_level: int,
    grid_price: float,
    order_qty: int,
    order_id: str | None = None,
    status: str = "pending",
) -> int:
    """插入交易记录，返回记录 ID。"""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO grid_orders "
        "(config_id, code, env, direction, grid_level, grid_price, order_qty, "
        "order_id, status, triggered_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (config_id, code, env, direction, grid_level, grid_price, order_qty,
         order_id, status, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def update_order_fill(row_id: int, fill_price: float, fill_qty: int, pnl: float | None = None) -> None:
    """更新成交信息。"""
    conn = _get_conn()
    conn.execute(
        "UPDATE grid_orders SET fill_price = ?, fill_qty = ?, pnl = ?, "
        "status = 'filled', filled_at = ? WHERE id = ?",
        (fill_price, fill_qty, pnl, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row_id),
    )
    conn.commit()
    conn.close()


def query_orders(config_id: int, limit: int = 50) -> list[dict]:
    """查询交易记录（最新在前）。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM grid_orders WHERE config_id = ? ORDER BY id DESC LIMIT ?",
        (config_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
