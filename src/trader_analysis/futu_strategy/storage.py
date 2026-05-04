"""持久化存储层。

所有 SQL 集中在此文件，其他模块不直接写 SQL。
使用 SQLite 存储 K 线 + 指标数据和评分结果，通过文件解耦后端（写入）与 API（读取）。
"""

from __future__ import annotations

import json
import os
import sqlite3

import pandas as pd

from trader_analysis.futu_strategy import config

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS kline_indicators (
    code         TEXT NOT NULL,
    ktype        TEXT NOT NULL,
    date         TEXT NOT NULL,
    open         REAL,
    high         REAL,
    low          REAL,
    close        REAL,
    volume       REAL,
    turnover     REAL,
    ma5          REAL,
    ma10         REAL,
    ma20         REAL,
    ma60         REAL,
    ma120        REAL,
    ma250        REAL,
    rsi14        REAL,
    dif          REAL,
    dea          REAL,
    macd         REAL,
    boll_upper   REAL,
    boll_mid     REAL,
    boll_lower   REAL,
    vol_ma20     REAL,
    updated_at   TEXT,
    PRIMARY KEY (code, ktype, date)
);

CREATE INDEX IF NOT EXISTS idx_code_ktype_date
    ON kline_indicators(code, ktype, date);

CREATE TABLE IF NOT EXISTS score_results (
    code         TEXT NOT NULL,
    date         TEXT NOT NULL,
    total_score  INTEGER,
    signal       TEXT,
    breakdown    TEXT,
    updated_at   TEXT,
    PRIMARY KEY (code, date)
);

CREATE TABLE IF NOT EXISTS market_score (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    date                TEXT NOT NULL UNIQUE,
    composite_score     REAL NOT NULL,
    target_position_pct REAL NOT NULL,
    extreme_triggered   INTEGER DEFAULT 0,
    leverage_tool       TEXT DEFAULT 'none',
    daily_tech_score    REAL,
    weekly_tech_score   REAL,
    vol_score           REAL,
    price_score         REAL,
    volume_score        REAL,
    safe_haven_score    REAL,
    spy_price           REAL,
    qqq_price           REAL,
    gld_price           REAL,
    vix_value           REAL,
    spy_daily_rsi       REAL,
    qqq_daily_rsi       REAL,
    spy_weekly_rsi      REAL,
    qqq_weekly_rsi      REAL,
    spy_ma200_dev       REAL,
    qqq_ma200_dev       REAL,
    spy_vol_ratio       REAL,
    qqq_vol_ratio       REAL,
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS market_score_detail (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL UNIQUE,
    detail_json TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);
"""

# K 线 + 指标列（写入顺序）
_KLINE_COLS = [
    "date", "open", "high", "low", "close", "volume", "turnover",
    "ma5", "ma10", "ma20", "ma60", "ma120", "ma250",
    "rsi14", "dif", "dea", "macd",
    "boll_upper", "boll_mid", "boll_lower", "vol_ma20",
]


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """建表（幂等），首次运行或数据库文件不存在时调用。"""
    conn = _get_conn()
    conn.executescript(_CREATE_TABLES_SQL)
    conn.close()


def batch_upsert(code: str, ktype: str, df: pd.DataFrame) -> int:
    """批量写入/更新 K 线 + 指标行，返回写入行数。"""
    conn = _get_conn()
    now = pd.Timestamp.now().isoformat()
    count = 0
    placeholders = ",".join(["?"] * (len(_KLINE_COLS) + 3))  # code, ktype, cols..., updated_at
    col_names = ",".join(["code", "ktype"] + _KLINE_COLS + ["updated_at"])
    sql = f"INSERT OR REPLACE INTO kline_indicators ({col_names}) VALUES ({placeholders})"

    # DataFrame 列名 → DB 列名映射（normalize_ohlcv 产出 "timestamp"，DB 存 "date"）
    col_map = {"date": "timestamp"}

    for _, row in df.iterrows():
        values = [code, ktype]
        for c in _KLINE_COLS:
            src = col_map.get(c, c)
            v = row.get(src)
            if pd.isna(v):
                values.append(None)
            elif isinstance(v, pd.Timestamp):
                values.append(v.strftime("%Y-%m-%d"))
            else:
                values.append(v)
        values.append(now)
        conn.execute(sql, values)
        count += 1

    conn.commit()
    conn.close()
    return count


def query_recent(code: str, ktype: str, limit: int = 250) -> pd.DataFrame:
    """读最近 N 根 K 线 + 指标，返回 DataFrame（日期升序）。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM kline_indicators WHERE code = ? AND ktype = ? "
        "ORDER BY date DESC LIMIT ?",
        (code, ktype, limit),
    ).fetchall()
    conn.close()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in reversed(rows)])


def get_latest_date(code: str, ktype: str) -> str | None:
    """查本地最新日期，无数据时返回 None。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT MAX(date) AS max_date FROM kline_indicators WHERE code = ? AND ktype = ?",
        (code, ktype),
    ).fetchone()
    conn.close()
    return row["max_date"] if row else None


def query_range(code: str, ktype: str, days: int = 60) -> list[dict]:
    """按天数查询最近 N 根，返回 list[dict]（日期升序），供 API 层使用。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume, "
        "ma5, ma10, ma20, ma60, ma120, ma250, "
        "rsi14, dif, dea, macd, "
        "boll_upper, boll_mid, boll_lower, vol_ma20 "
        "FROM kline_indicators WHERE code = ? AND ktype = ? "
        "ORDER BY date DESC LIMIT ?",
        (code, ktype, days),
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def query_latest(code: str, ktype: str) -> dict:
    """查最新一根 K 线 + 指标。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM kline_indicators WHERE code = ? AND ktype = ? "
        "ORDER BY date DESC LIMIT 1",
        (code, ktype),
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


def list_codes() -> list[str]:
    """列出所有已入库标的。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT code FROM kline_indicators ORDER BY code"
    ).fetchall()
    conn.close()
    return [r["code"] for r in rows]


def upsert_score(code: str, date: str, result: dict) -> None:
    """写入/更新评分结果。"""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO score_results "
        "(code, date, total_score, signal, breakdown, updated_at) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'))",
        (
            code,
            date,
            result["total_score"],
            result["signal"],
            json.dumps(result.get("breakdown", {}), ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()


def query_latest_score(code: str) -> dict:
    """查最新评分结果。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM score_results WHERE code = ? ORDER BY date DESC LIMIT 1",
        (code,),
    ).fetchone()
    conn.close()
    if row:
        d = dict(row)
        d["breakdown"] = json.loads(d["breakdown"]) if d.get("breakdown") else {}
        return d
    return {}


# ── 市场温度（Market Temperature）──────────────────────────────────────────────


def upsert_market_score(date: str, result: dict) -> None:
    """写入/更新市场温度评分。"""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO market_score "
        "(date, composite_score, target_position_pct, extreme_triggered, leverage_tool, "
        "daily_tech_score, weekly_tech_score, vol_score, price_score, volume_score, safe_haven_score, "
        "spy_price, qqq_price, gld_price, vix_value, "
        "spy_daily_rsi, qqq_daily_rsi, spy_weekly_rsi, qqq_weekly_rsi, "
        "spy_ma200_dev, qqq_ma200_dev, spy_vol_ratio, qqq_vol_ratio) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            date,
            result["composite_score"],
            result["target_position_pct"],
            int(result.get("extreme_triggered", False)),
            result.get("leverage_tool", "none"),
            result.get("daily_tech_score"),
            result.get("weekly_tech_score"),
            result.get("vol_score"),
            result.get("price_score"),
            result.get("volume_score"),
            result.get("safe_haven_score"),
            result.get("spy_price"),
            result.get("qqq_price"),
            result.get("gld_price"),
            result.get("vix_value"),
            result.get("spy_daily_rsi"),
            result.get("qqq_daily_rsi"),
            result.get("spy_weekly_rsi"),
            result.get("qqq_weekly_rsi"),
            result.get("spy_ma200_dev"),
            result.get("qqq_ma200_dev"),
            result.get("spy_vol_ratio"),
            result.get("qqq_vol_ratio"),
        ),
    )
    # 同时写入明细 JSON
    detail_json = json.dumps(result.get("detail", {}), ensure_ascii=False)
    conn.execute(
        "INSERT OR REPLACE INTO market_score_detail (date, detail_json) VALUES (?, ?)",
        (date, detail_json),
    )
    conn.commit()
    conn.close()


def query_latest_market_score() -> dict:
    """查最新一条市场温度评分。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT m.*, d.detail_json FROM market_score m "
        "LEFT JOIN market_score_detail d ON m.date = d.date "
        "ORDER BY m.date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return {}
    result = dict(row)
    result["extreme_triggered"] = bool(result.get("extreme_triggered"))
    if result.get("detail_json"):
        result["detail"] = json.loads(result["detail_json"])
    else:
        result["detail"] = {}
    result.pop("detail_json", None)
    result.pop("id", None)
    return result


def query_market_score_history(days: int = 30) -> list[dict]:
    """查近 N 天市场温度历史（日期升序）。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT date, composite_score, target_position_pct, extreme_triggered, leverage_tool, "
        "daily_tech_score, weekly_tech_score, vol_score, price_score, volume_score, safe_haven_score "
        "FROM market_score ORDER BY date DESC LIMIT ?",
        (days,),
    ).fetchall()
    conn.close()
    result = [dict(r) for r in reversed(rows)]
    for item in result:
        item["extreme_triggered"] = bool(item.get("extreme_triggered"))
    return result
