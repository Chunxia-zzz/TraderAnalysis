# Part B — 持久化存储层（storage.py / init_history.py / daily_update.py）

> 存储层是后端（写入方）与 API 服务（读取方）之间的桥梁。后端将 K 线和计算好的指标写入本地数据库，API 层直接读取返回，两者通过 SQLite 文件解耦。

---

## 功能清单

### 数据库设计

| # | 功能 | 实现方式 |
|---|------|---------|
| F1 | 存储 K 线原始数据 + 全部技术指标值 | SQLite `kline_indicators` 表 |
| F2 | 支持多标的、多周期（日线/周线）共存 | 主键 `(code, ktype, date)` |
| F3 | 按标的+周期+日期范围快速查询 | 索引 `idx_code_ktype_date` |
| F4 | 存储评分结果供 API 读取 | SQLite `score_results` 表 |

### 历史初始化

| # | 功能 | 实现方式 |
|---|------|---------|
| G1 | 一次性拉取所有标的的历史 K 线 | 调用 data_fetcher（外部数据） |
| G2 | 计算全部历史指标 | 调用 indicators.calc_indicators（自实现） |
| G3 | 批量写入数据库 | 调用 storage.batch_upsert（自实现） |

### 每日增量更新

| # | 功能 | 实现方式 |
|---|------|---------|
| H1 | 查询各标的本地最新日期 | storage.get_latest_date（自实现） |
| H2 | 只拉取新增的 K 线 | 调用 data_fetcher（外部数据） |
| H3 | 与历史数据拼接后重新计算末尾指标 | 调用 storage.query_recent + indicators（自实现） |
| H4 | UPSERT 最新行到数据库 | storage.upsert（自实现） |

### 存储层读写接口

| # | 函数 | 用途 | 调用方 |
|---|------|------|--------|
| I1 | `init_db()` | 建表（幂等，首次运行） | init_history |
| I2 | `batch_upsert(code, ktype, df)` | 批量写入/更新 | init_history / daily_update |
| I3 | `query_recent(code, ktype, limit)` | 读最近 N 根 | daily_update |
| I4 | `get_latest_date(code, ktype)` | 查最新日期 | daily_update |
| I5 | `query_range(code, ktype, days)` | 按天数范围查询 | api_server |
| I6 | `query_latest(code, ktype)` | 查最新一根 | api_server |
| I7 | `list_codes()` | 列出所有已入库标的 | api_server |
| I8 | `upsert_score(code, date, result)` | 写入评分结果 | scorer |
| I9 | `query_latest_score(code)` | 查最新评分 | api_server |

---

## 实现思路

- 使用 **SQLite**：零配置，单文件，Python 原生支持
- K 线和指标**合并存储**在同一张表（一行 = 一根 K 线 + 该根的所有指标值）
- 主键 `(code, ktype, date)` 保证数据不重复，`INSERT OR REPLACE` 实现 UPSERT
- 所有 SQL 集中在 `storage.py`，其他模块不直接写 SQL（未来换存储引擎只改此文件）
- **增量更新关键约束**：不能只用新的 1 根 K 线计算指标，必须拼接历史再算

---

## 具体实现方案

### 数据库表结构

**K 线 + 指标表：**

```sql
CREATE TABLE IF NOT EXISTS kline_indicators (
    code         TEXT NOT NULL,      -- 'HK.00700'
    ktype        TEXT NOT NULL,      -- '1d' / '1w'
    date         TEXT NOT NULL,      -- '2026-04-14'
    -- 原始 K 线
    open         REAL,
    high         REAL,
    low          REAL,
    close        REAL,
    volume       REAL,
    turnover     REAL,
    -- 均线
    ma5          REAL,
    ma10         REAL,
    ma20         REAL,
    ma60         REAL,
    ma120        REAL,
    ma250        REAL,
    -- RSI
    rsi14        REAL,
    -- MACD
    dif          REAL,
    dea          REAL,
    macd         REAL,
    -- 布林带
    boll_upper   REAL,
    boll_mid     REAL,
    boll_lower   REAL,
    -- 成交量均线
    vol_ma20     REAL,
    -- 元数据
    updated_at   TEXT,

    PRIMARY KEY (code, ktype, date)
);

CREATE INDEX IF NOT EXISTS idx_code_ktype_date ON kline_indicators(code, ktype, date);
```

**评分结果表：**

```sql
CREATE TABLE IF NOT EXISTS score_results (
    code         TEXT NOT NULL,
    date         TEXT NOT NULL,
    total_score  INTEGER,
    signal       TEXT,               -- 'STRONG_BUY' / 'BUY' / 'NO_ACTION'
    breakdown    TEXT,               -- JSON 字符串
    updated_at   TEXT,

    PRIMARY KEY (code, date)
);
```

---

### storage.py 接口实现（自实现，纯 Python + sqlite3）

```python
import sqlite3
import pandas as pd
import json, os

DB_PATH = os.environ.get('DB_PATH', 'data/indicators.db')

def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """建表，幂等操作，可重复调用"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS kline_indicators (...);  -- 完整 DDL 见上方
        CREATE TABLE IF NOT EXISTS score_results (...);
        CREATE INDEX IF NOT EXISTS idx_code_ktype_date ON kline_indicators(code, ktype, date);
    """)
    conn.close()

def batch_upsert(code: str, ktype: str, df: pd.DataFrame):
    """批量写入，主键冲突时覆盖"""
    conn = get_conn()
    cols = ['date','open','high','low','close','volume','turnover',
            'ma5','ma10','ma20','ma60','ma120','ma250','rsi14',
            'dif','dea','macd','boll_upper','boll_mid','boll_lower','vol_ma20']
    for _, row in df.iterrows():
        values = [code, ktype] + [row.get(c) for c in cols] + [pd.Timestamp.now().isoformat()]
        placeholders = ','.join(['?'] * (len(cols) + 3))
        conn.execute(f"""
            INSERT OR REPLACE INTO kline_indicators
            (code, ktype, {','.join(cols)}, updated_at)
            VALUES ({placeholders})
        """, values)
    conn.commit()
    conn.close()

def query_recent(code: str, ktype: str, limit: int = 250) -> pd.DataFrame:
    """读最近 N 根，返回 DataFrame（日期升序）"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM kline_indicators
        WHERE code = ? AND ktype = ?
        ORDER BY date DESC LIMIT ?
    """, (code, ktype, limit)).fetchall()
    conn.close()
    df = pd.DataFrame([dict(r) for r in reversed(rows)])
    return df

def get_latest_date(code: str, ktype: str) -> str | None:
    """查本地最新日期"""
    conn = get_conn()
    row = conn.execute("""
        SELECT MAX(date) as max_date FROM kline_indicators
        WHERE code = ? AND ktype = ?
    """, (code, ktype)).fetchone()
    conn.close()
    return row['max_date'] if row else None

def query_range(code: str, ktype: str, days: int = 60) -> list[dict]:
    """按天数查询最近 N 根，返回 list[dict]（日期升序），供 API 层使用"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT date, open, high, low, close, volume,
               ma5, ma10, ma20, ma60, ma120, ma250,
               rsi14, dif, dea, macd,
               boll_upper, boll_mid, boll_lower, vol_ma20
        FROM kline_indicators
        WHERE code = ? AND ktype = ?
        ORDER BY date DESC LIMIT ?
    """, (code, ktype, days)).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]

def query_latest(code: str, ktype: str) -> dict:
    """查最新一根"""
    conn = get_conn()
    row = conn.execute("""
        SELECT * FROM kline_indicators
        WHERE code = ? AND ktype = ?
        ORDER BY date DESC LIMIT 1
    """, (code, ktype)).fetchone()
    conn.close()
    return dict(row) if row else {}

def list_codes() -> list[str]:
    """列出所有已入库标的"""
    conn = get_conn()
    rows = conn.execute("SELECT DISTINCT code FROM kline_indicators ORDER BY code").fetchall()
    conn.close()
    return [r['code'] for r in rows]

def upsert_score(code: str, date: str, result: dict):
    """写入评分结果"""
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO score_results (code, date, total_score, signal, breakdown, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
    """, (code, date, result['total_score'], result['signal'], json.dumps(result['breakdown'])))
    conn.commit()
    conn.close()

def query_latest_score(code: str) -> dict:
    """查最新评分"""
    conn = get_conn()
    row = conn.execute("""
        SELECT * FROM score_results WHERE code = ? ORDER BY date DESC LIMIT 1
    """, (code,)).fetchone()
    conn.close()
    if row:
        d = dict(row)
        d['breakdown'] = json.loads(d['breakdown']) if d.get('breakdown') else {}
        return d
    return {}
```

---

### init_history.py — 历史初始化脚本（自实现）

支持**断点续传**和**频率控制**，40 只标的中途中断后重新运行即可从断点继续。

```
python -m trader_analysis init                        # 全部 watchlist
python -m trader_analysis init --codes US.AAPL US.TSLA  # 指定标的
python -m trader_analysis init --force                 # 强制重拉全部

执行流程：
  1. storage.init_db() 建表
  2. 检查已有数据标的（日线+周线均有则跳过，支持断点续传）
  3. 检查历史 K 线额度（需 >= 待拉取标的数 × 2）
  4. for each pending code（每次请求间隔 3 秒，避免触发频率限制）:
     a. data_fetcher 拉取 1000 根日线 + 200 根周线（API 单次上限）
     b. calc_indicators(daily_df, DAILY_INDICATOR_CONFIG)
     c. calc_indicators(weekly_df, WEEKLY_INDICATOR_CONFIG)
     d. storage.batch_upsert(code, '1d', daily_df)
     e. storage.batch_upsert(code, '1w', weekly_df)
  5. 输出结果摘要（成功/失败数量），失败的标的重新运行即可
```

**--force 参数**：忽略已有数据，强制重新拉取所有标的。用于数据库重建场景。

---

### daily_update.py — 每日增量更新脚本（自实现）

```
python daily_update.py（由定时任务触发）

执行流程：
  1. for each code in config.WATCHLIST:
     a. last_date = storage.get_latest_date(code, '1d')
     b. 如果 last_date 为 None → 提示需先运行 init_history.py
     c. data_fetcher 拉取 last_date 之后的新 K 线
     d. 如果无新数据 → 跳过
     e. history_df = storage.query_recent(code, '1d', limit=300)
     f. 拼接 history_df + new_df
     g. merged_df = calc_indicators(merged, DAILY_INDICATOR_CONFIG)
     h. 只取新增行 → storage.batch_upsert(code, '1d', new_rows)
  2. 周线同理
  3. 输出更新摘要
```

> **关键点**：增量更新时必须读出本地最近 300 根历史数据与新数据拼接后统一计算。MA250 回望 250 根，MA120 回望 120 根，RSI 预热 ~14 根，MACD 预热 ~60 根——只用 1 根新数据计算指标会严重偏差。
