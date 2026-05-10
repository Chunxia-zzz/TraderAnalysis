"""标的池持久化存储层。

管理 watchlist 表的 DDL 与 CRUD 操作。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from trader_analysis.futu_strategy import config

_CREATE_WATCHLIST_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS watchlist (
    code            TEXT PRIMARY KEY,
    ticker          TEXT NOT NULL,
    name            TEXT NOT NULL,
    market          TEXT NOT NULL,
    sector          TEXT,
    industry        TEXT,
    listing_date    TEXT,

    category        TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'watching',
    tags            TEXT DEFAULT '[]',

    target_price    REAL,
    stop_loss       REAL,
    analyst_target_mean   REAL,
    morningstar_fair_value REAL,

    forward_pe      REAL,
    forward_eps     REAL,
    peg_ratio       REAL,
    revenue_growth  REAL,
    earnings_growth REAL,
    profit_margin   REAL,
    roe             REAL,
    debt_to_equity  REAL,

    trailing_pe     REAL,
    market_cap      REAL,
    current_price   REAL,
    dividend_yield  REAL,
    beta            REAL,

    thesis          TEXT DEFAULT '',
    notes           TEXT DEFAULT '',
    recommended_strategy TEXT DEFAULT '',

    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_watchlist_category ON watchlist(category);
CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist(status);
CREATE INDEX IF NOT EXISTS idx_watchlist_market ON watchlist(market);
"""

EDITABLE_FIELDS = [
    "category", "status", "tags",
    "target_price", "stop_loss",
    "analyst_target_mean", "morningstar_fair_value",
    "forward_pe", "forward_eps", "peg_ratio",
    "revenue_growth", "earnings_growth",
    "profit_margin", "roe", "debt_to_equity",
    "thesis", "notes", "recommended_strategy",
]

READONLY_FIELDS = [
    "code", "ticker", "name", "market",
    "sector", "industry", "listing_date",
    "trailing_pe", "market_cap", "current_price",
    "dividend_yield", "beta",
    "created_at",
]

SNAPSHOT_FIELDS = [
    "trailing_pe", "market_cap", "current_price",
    "dividend_yield", "beta",
]


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    """将 Row 转为 dict，tags 字段反序列化为 list。"""
    d = dict(row)
    if "tags" in d and isinstance(d["tags"], str):
        try:
            d["tags"] = json.loads(d["tags"])
        except (json.JSONDecodeError, TypeError):
            d["tags"] = []
    return d


def init_watchlist_table() -> None:
    """创建 watchlist 表（幂等）。"""
    conn = _get_conn()
    try:
        conn.executescript(_CREATE_WATCHLIST_TABLE_SQL)
    finally:
        conn.close()


def list_watchlist(
    category: str | None = None,
    status: str | None = None,
    market: str | None = None,
    search: str | None = None,
) -> list[dict]:
    """查询标的列表，支持筛选。"""
    conn = _get_conn()
    try:
        sql = "SELECT * FROM watchlist WHERE 1=1"
        params: list = []

        if category:
            sql += " AND category = ?"
            params.append(category)
        if status:
            sql += " AND status = ?"
            params.append(status)
        if market:
            sql += " AND market = ?"
            params.append(market)
        if search:
            sql += " AND (ticker LIKE ? OR name LIKE ? OR notes LIKE ?)"
            pattern = f"%{search}%"
            params.extend([pattern, pattern, pattern])

        sql += " ORDER BY category, code"
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_stock(code: str) -> dict | None:
    """查询单只标的。"""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM watchlist WHERE code = ?", (code,)).fetchone()
        if row is None:
            return None
        return _row_to_dict(row)
    finally:
        conn.close()


def add_stock(data: dict) -> dict:
    """新增标的，返回完整记录。"""
    code = data["code"]
    parts = code.split(".", 1)
    market = parts[0] if len(parts) == 2 else "US"
    ticker = parts[1] if len(parts) == 2 else code

    tags_str = json.dumps(data.get("tags", []), ensure_ascii=False)

    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO watchlist
               (code, ticker, name, market, sector, industry, listing_date,
                category, status, tags, target_price, stop_loss, thesis, notes,
                trailing_pe, market_cap, current_price, dividend_yield, beta)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                code,
                data.get("ticker", ticker),
                data.get("name", ticker),
                data.get("market", market),
                data.get("sector"),
                data.get("industry"),
                data.get("listing_date"),
                data.get("category", ""),
                data.get("status", "watching"),
                tags_str,
                data.get("target_price"),
                data.get("stop_loss"),
                data.get("thesis", ""),
                data.get("notes", ""),
                data.get("trailing_pe"),
                data.get("market_cap"),
                data.get("current_price"),
                data.get("dividend_yield"),
                data.get("beta"),
            ),
        )
        conn.commit()
        return get_stock(code)  # type: ignore
    finally:
        conn.close()


def update_stock(code: str, fields: dict) -> tuple[dict | None, list[str]]:
    """更新标的可编辑字段。返回 (更新后记录, 实际更新的字段列表)。"""
    # 检查只读字段
    readonly_violations = [f for f in fields if f in READONLY_FIELDS]
    if readonly_violations:
        return None, readonly_violations

    # 过滤掉不在可编辑列表中的字段
    valid_fields = {k: v for k, v in fields.items() if k in EDITABLE_FIELDS}
    if not valid_fields:
        return get_stock(code), []

    # tags 特殊处理
    if "tags" in valid_fields:
        valid_fields["tags"] = json.dumps(valid_fields["tags"], ensure_ascii=False)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    valid_fields["updated_at"] = now

    set_clause = ", ".join(f"{k} = ?" for k in valid_fields)
    values = list(valid_fields.values()) + [code]

    conn = _get_conn()
    try:
        conn.execute(f"UPDATE watchlist SET {set_clause} WHERE code = ?", values)
        conn.commit()
        updated_keys = [k for k in valid_fields if k != "updated_at"]
        return get_stock(code), updated_keys
    finally:
        conn.close()


def delete_stock(code: str) -> bool:
    """删除标的（幂等）。"""
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM watchlist WHERE code = ?", (code,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def batch_add(codes: list[str], defaults: dict | None = None) -> tuple[list[str], list[str]]:
    """批量新增。返回 (added, skipped)。"""
    defaults = defaults or {}
    added = []
    skipped = []
    for code in codes:
        existing = get_stock(code)
        if existing:
            skipped.append(code)
            continue
        data = {**defaults, "code": code}
        add_stock(data)
        added.append(code)
    return added, skipped


def refresh_snapshot(code: str, snapshot_data: dict) -> None:
    """更新静态快照字段（trailing_pe, market_cap 等）。"""
    valid = {k: v for k, v in snapshot_data.items() if k in SNAPSHOT_FIELDS}
    if not valid:
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    valid["updated_at"] = now

    set_clause = ", ".join(f"{k} = ?" for k in valid)
    values = list(valid.values()) + [code]

    conn = _get_conn()
    try:
        conn.execute(f"UPDATE watchlist SET {set_clause} WHERE code = ?", values)
        conn.commit()
    finally:
        conn.close()


def get_all_codes(exclude_exited: bool = True) -> list[str]:
    """获取所有标的 code 列表（默认排除 exited 状态）。"""
    conn = _get_conn()
    try:
        if exclude_exited:
            rows = conn.execute(
                "SELECT code FROM watchlist WHERE status != 'exited' ORDER BY code"
            ).fetchall()
        else:
            rows = conn.execute("SELECT code FROM watchlist ORDER BY code").fetchall()
        return [r["code"] for r in rows]
    finally:
        conn.close()


def get_watchlist_detail() -> list[dict]:
    """获取完整标的列表（用于替代 config.WATCHLIST_DETAIL）。"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM watchlist WHERE status != 'exited' ORDER BY category, code"
        ).fetchall()
        results = []
        for r in rows:
            d = _row_to_dict(r)
            d["futu_code"] = d["code"]
            results.append(d)
        return results
    finally:
        conn.close()


def watchlist_count() -> int:
    """返回 watchlist 表中的记录数。"""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT COUNT(*) as cnt FROM watchlist").fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


def migrate_from_json(items: list[dict], categories: dict) -> int:
    """从 watchlist.json 格式批量导入。返回导入数量。"""
    count = 0
    for item in items:
        market = item["market"]
        ticker = item["ticker"]
        code = f"{market}.{ticker}"

        if get_stock(code):
            continue

        tags_str = json.dumps(item.get("tags", []), ensure_ascii=False)

        conn = _get_conn()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO watchlist
                   (code, ticker, name, market, category, status, tags,
                    target_price, stop_loss, thesis, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    code,
                    ticker,
                    item.get("name", ticker),
                    market,
                    item.get("category", ""),
                    item.get("status", "watching"),
                    tags_str,
                    item.get("target_price"),
                    item.get("stop_loss"),
                    item.get("thesis", ""),
                    item.get("notes", ""),
                ),
            )
            conn.commit()
            count += 1
        finally:
            conn.close()
    return count
