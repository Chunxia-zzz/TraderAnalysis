# Part B — 持久化存储层（storage.py / init_history.py / daily_update.py）

> 存储层是后端（写入方）与 API 服务（读取方）之间的桥梁。后端将 K 线、计算好的指标、评分、信号、持仓状态写入本地 SQLite，API 层直接读取返回，两者通过**同一个 DB 文件**解耦。
>
> 源码位置：`src/trader_analysis/futu_strategy/{storage,init_history,daily_update}.py`

---

## 功能清单

### 数据库设计

| # | 功能 | 实现方式 |
|---|------|---------|
| F1 | 存储 K 线原始数据 + 全部技术指标值 | SQLite `kline_indicators` 表 |
| F2 | 支持多标的、多周期（日线/周线/4小时）共存 | 主键 `(code, ktype, date)` |
| F3 | 按标的+周期+日期范围快速查询 | 索引 `idx_code_ktype_date` |
| F4 | 存储个股评分结果供 API 读取 | SQLite `score_results` 表 |
| F5 | 存储大盘温度（市场评分）结果 | `market_score` + `market_score_detail` 表 |
| F6 | 存储基本面/估值数据 | `fundamental_data` 表 |
| F7 | 存储信号日志（顶部/底部/利弗莫尔） | `top_signal_log` / `bottom_signal_log` / `livermore_signal_log` |
| F8 | 存储交易模块持仓状态机 | `position_state` 表 |

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
| H3 | 与历史数据拼接后重新计算全段指标 | storage.query_recent + indicators（自实现） |
| H4 | UPSERT 最新行到数据库 | storage.batch_upsert（自实现） |

### 存储层读写接口（`storage.py` 全部函数）

| 分组 | 函数 | 用途 |
|------|------|------|
| 建库 | `init_db()` | 建表 + 建索引（幂等，首次运行） |
| K 线 | `batch_upsert(code, ktype, df) -> int` | 批量写入/更新，返回写入行数 |
| K 线 | `query_recent(code, ktype, limit=250) -> DataFrame` | 读最近 N 根（日期升序） |
| K 线 | `get_latest_date(code, ktype) -> str \| None` | 查最新日期 |
| K 线 | `query_range(code, ktype, days=60) -> list[dict]` | 按根数查询，供 API 层使用 |
| K 线 | `query_latest(code, ktype) -> dict` | 查最新一根 |
| K 线 | `list_codes() -> list[str]` | 列出所有已入库标的 |
| 评分 | `upsert_score(code, date, result)` | 写入个股评分结果 |
| 评分 | `query_latest_score(code) -> dict` | 查最新评分（`breakdown` 已反序列化） |
| 评分 | `query_score_by_date(code, date) -> dict` | 查指定日评分 |
| 评分 | `query_scores_overview(date=None) -> list[dict]` | 全池评分概览（指定日或最新日） |
| 温度 | `upsert_market_score(date, result)` | 写入大盘温度 |
| 温度 | `query_latest_market_score() -> dict` | 查最新温度 |
| 温度 | `query_market_score_history(days=30) -> list[dict]` | 温度历史曲线 |
| 基本面 | `upsert_fundamental(code, date, data)` | 写入基本面数据 |
| 基本面 | `query_latest_fundamental(code) -> dict \| None` | 查最新基本面 |
| 基本面 | `query_fundamentals_overview() -> list[dict]` | 全池基本面概览 |
| 联表 | `query_all_scores(code, start, end)` | 个股评分序列 |
| 联表 | `query_close_prices(code, start, end)` | 收盘价序列 |
| 联表 | `query_price_and_ma(code, ma_col="ma5", start, end)` | 价格 + 指定均线 |
| 联表 | `query_ema_ribbon_data(code, start, end)` | EMA 飘带全段数据 |
| 联表 | `query_trading_dates(code, start, end)` | 交易日列表 |
| 信号 | `insert_top_signal(...)` / `query_top_signals(code, days)` / `query_top_signals_all(days)` | 顶部信号写入与查询 |
| 信号 | `insert_bottom_signal(...)` / `query_bottom_signals(code, days)` / `query_bottom_signals_all(days)` | 底部信号写入与查询 |
| 信号 | `insert_livermore_signal(...)` / `query_livermore_signals(...)` / `query_livermore_dates(limit)` / `delete_livermore_signals(code, date)` | 利弗莫尔关键点信号 |
| 仓位 | `get_position_state(code)` / `upsert_position_state(...)` / `list_active_positions()` / `reset_position_state(code)` | 持仓状态机 |

---

## 实现思路

- 使用 **SQLite**：零配置，单文件，Python 原生支持
- K 线和指标**合并存储**在同一张表（一行 = 一根 K 线 + 该根的所有指标值）
- 主键 `(code, ktype, date)` 保证数据不重复，`INSERT OR REPLACE` 实现 UPSERT
- 所有 SQL 集中在 `storage.py`，其他模块不直接写 SQL（未来换存储引擎只改此文件）
- 数据库路径来自 `config.DB_PATH`，可用环境变量 **`TA_DB_PATH`** 覆盖（默认 `<项目根>/data/indicators.db`）——**注意不是 `DB_PATH` 环境变量**
- **增量更新关键约束**：不能只用新的 1 根 K 线计算指标，必须拼接历史再算

---

## 具体实现方案

### 数据库表结构（共 9 张表）

`storage.py` 中的 `_CREATE_TABLES_SQL` 一次 `executescript` 建全表：

| 表名 | 用途 | 主键/唯一约束 |
|------|------|--------------|
| `kline_indicators` | K 线 + 全部技术指标 | PK `(code, ktype, date)` |
| `score_results` | 个股评分 | PK `(code, date)` |
| `market_score` | 大盘温度（宽表） | PK `id` 自增，`date` UNIQUE |
| `market_score_detail` | 大盘温度明细 JSON | PK `id` 自增，`date` UNIQUE |
| `fundamental_data` | 基本面 + 估值 | PK `(code, date)` |
| `position_state` | 交易模块持仓状态机 | PK `code` |
| `top_signal_log` | 顶部预警信号 | PK `id` 自增，**无唯一约束** |
| `bottom_signal_log` | 底部信号 | PK `id` 自增，**无唯一约束** |
| `livermore_signal_log` | 利弗莫尔关键点信号 | PK `id` 自增，**有 UNIQUE(code, date, signal_type)** |

> ⚠️ **唯一约束差异是重要坑**：`top/bottom_signal_log` 没有唯一约束，重跑 `scan-signals` 会导致信号翻倍；`livermore_signal_log` 建了 UNIQUE 索引并用 `INSERT OR REPLACE`，重跑幂等。

**K 线 + 指标表（实际 DDL 简化版）：**

```sql
CREATE TABLE IF NOT EXISTS kline_indicators (
    code         TEXT NOT NULL,      -- 'HK.00700'
    ktype        TEXT NOT NULL,      -- '1d' / '1w' / '4h'
    date         TEXT NOT NULL,      -- '2026-04-14'（4h 为 'YYYY-MM-DD HH:MM:SS'）
    -- 原始 K 线
    open REAL, high REAL, low REAL, close REAL, volume REAL, turnover REAL,
    -- 均线
    ma5 REAL, ma10 REAL, ma20 REAL, ma60 REAL, ma120 REAL, ma200 REAL, ma250 REAL,
    -- RSI（三周期，非单一 rsi14）
    rsi6 REAL, rsi12 REAL, rsi24 REAL,
    -- MACD
    dif REAL, dea REAL, macd REAL,
    -- 布林带
    boll_upper REAL, boll_mid REAL, boll_lower REAL,
    -- 成交量均线
    vol_ma20 REAL,
    -- EMA（多空飘带）
    ema5 REAL, ema10 REAL, ema15 REAL, ema20 REAL, ema25 REAL, ema30 REAL,
    -- ATR（止盈止损基准）
    atr14 REAL,
    updated_at   TEXT,
    PRIMARY KEY (code, ktype, date)
);

CREATE INDEX IF NOT EXISTS idx_code_ktype_date ON kline_indicators(code, ktype, date);
```

**个股评分表：**

```sql
CREATE TABLE IF NOT EXISTS score_results (
    code         TEXT NOT NULL,
    date         TEXT NOT NULL,
    total_score  INTEGER,            -- 0-100（6 因子加权 + 温度加成）
    signal       TEXT,               -- 'STRONG_BUY' / 'BUY' / 'NO_ACTION'
    breakdown    TEXT,               -- JSON 字符串（各因子得分明细）
    updated_at   TEXT,
    PRIMARY KEY (code, date)
);
```

**大盘温度表：** `market_score` 为宽表，含 `composite_score`、`target_position_pct`、`extreme_triggered`、`leverage_tool`、四类子分（`daily_tech_score` / `weekly_tech_score` / `vol_score` / `price_score` / `volume_score` / `safe_haven_score`）、以及 SPY/QQQ/GLD/VIX 的价格与 RSI、MA200 偏离、量比等原始输入列；`market_score_detail` 单独存完整 `detail_json`。

**基本面表：** `fundamental_data` 含估值（PE/PB/PEG/EV-EBITDA）、成长（revenue/earnings growth）、分析师目标价四件套（`target_mean/median/high/low` + `analyst_count` + `recommendation`）、财务健康（流动比/负债率/现金流/利润率/ROE）、市场属性（市值/股息率/beta/做空比），以及 `fundamental_score` + `valuation_signal` + `breakdown`。

**信号表：** 三张信号表结构相似（`code/date/signal_type/strength/detail_json/created_at`）；`livermore_signal_log` 额外有 `pivotal`（关键点价）、`close`、`dist_pct`、`vol_ratio`、`tide`（周线潮汐）、`wave`（日线波浪）、`context`、`rs_60`（相对强度）、`is_leader`、`stop`（止损位）等专有列。

**持仓状态表：** `position_state` 存 `stage`（HOLD/ADD/TRIM/EXIT 等）、`total_qty`、`remaining_qty`、`avg_cost`、`entry_date`、`last_signal`、`last_signal_date`。

---

### storage.py 主要接口实现（自实现，纯 Python + sqlite3）

```python
from trader_analysis.futu_strategy import config

def _get_conn() -> sqlite3.Connection:
    """注意：函数名是 _get_conn（下划线私有），不是 get_conn"""
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    """建表 + 建索引，幂等操作，可重复调用"""
    conn = _get_conn()
    conn.executescript(_CREATE_TABLES_SQL)   # 9 张表 + 全部索引
    conn.commit()
    conn.close()

_KLINE_COLS = [
    "date", "open", "high", "low", "close", "volume", "turnover",
    "ma5", "ma10", "ma20", "ma60", "ma120", "ma200", "ma250",
    "rsi6", "rsi12", "rsi24", "dif", "dea", "macd",
    "boll_upper", "boll_mid", "boll_lower", "vol_ma20",
    "ema5", "ema10", "ema15", "ema20", "ema25", "ema30",
    "atr14",
]

def batch_upsert(code: str, ktype: str, df: pd.DataFrame) -> int:
    """批量写入，主键冲突时覆盖；返回实际写入行数"""
    ...

def query_recent(code: str, ktype: str, limit: int = 250) -> pd.DataFrame:
    """读最近 N 根，返回 DataFrame（日期升序）"""
    ...

def get_latest_date(code: str, ktype: str) -> str | None:
    """查本地最新日期"""
    ...

def query_range(code: str, ktype: str, days: int = 60) -> list[dict]:
    """按根数查询，返回 list[dict]（日期升序），供 API 层使用"""
    ...

def query_latest(code: str, ktype: str) -> dict:
    """查最新一根"""
    ...

def list_codes() -> list[str]:
    """列出所有已入库标的"""
    ...

def upsert_score(code: str, date: str, result: dict) -> None:
    """写入个股评分结果（breakdown 序列化为 JSON）"""
    ...

def query_latest_score(code: str) -> dict:
    """查最新评分，breakdown 反序列化后返回"""
    ...
```

> 完整函数清单见上文「存储层读写接口」表；其余温度/基本面/信号/仓位函数命名同构（`upsert_*` / `query_*` / `insert_*`）。

---

### init_history.py — 历史初始化脚本（自实现）

支持**断点续传**和**频率控制**，中途中断后重新运行即可从断点继续。

```
python -m trader_analysis.futu_strategy.init_history                  # 全部 watchlist
python -m trader_analysis.futu_strategy.init_history --codes US.AAPL US.TSLA
python -m trader_analysis.futu_strategy.init_history --force          # 强制重拉全部
python -m trader_analysis.futu_strategy.init_history --start 2015-01-01

入口：run_init(codes: list[str], *, force: bool = False, start: str | None = None)

执行流程：
  1. storage.init_db() 建表
  2. 非 --force 时检查已有数据标的（日线+周线均有则跳过，支持断点续传）
  3. 若全部已有数据 → 提示「如需强制重建请加 --force」并退出
  4. for each pending code（每请求间 sleep _REQUEST_DELAY，避免触发频率限制）:
     a. data_fetcher 拉取日线 / 周线
     b. calc_indicators(daily_df, DAILY_INDICATOR_CONFIG)
     c. calc_indicators(weekly_df, WEEKLY_INDICATOR_CONFIG)
     d. storage.batch_upsert(code, '1d', daily_df)
     e. storage.batch_upsert(code, '1w', weekly_df)
  5. 输出结果摘要（成功/失败数量），失败的标的重新运行即可
```

**`--force` 参数**：忽略已有数据，强制重新拉取所有标的。用于数据库重建场景。
**`--start` 参数**：指定历史起点日期（不传则由 provider 默认，受富途单次根数上限约束）。

> ⚠️ 若要拉取超过富途默认 250 根的历史，必须在 `get_kline` 中**显式传 `start`**，否则 `max_count` 会被忽略。

---

### daily_update.py — 每日增量更新脚本（自实现）

```
python -m trader_analysis.futu_strategy.daily_update
（也由 runner.py 在评分前调用）

执行流程：
  1. init_db()（幂等）
  2. for each code in 待更新标的:
     a. 对每个周期（1d / 1w / 4h）调用 _update_ktype：
        - last_date = get_latest_date(code, ktype)
          · last_date 为 None → 警告「请先运行 init_history.py」并跳过本周期
        - 增量拉取根数 = min(max_count, {'1d': 30, '1w': 10, '4h': 60}[ktype])
          （只需覆盖约 1 个月缺口，避免浪费富途行情额度）
        - provider.get_kline(...) → 统一列名为 date（timestamp / time_key 均兼容）
          · 4h 周期格式化为 'YYYY-MM-DD HH:MM:SS'
        - **丢弃尚未收盘的 K 线**：filter_closed_bars(new_df, ktype, code)
          （规则见 `market_clock.py`：1d 需过本地 16:00、1w 需过周五 16:00、4h 需过其结束时刻）
        - 过滤出比 last_date 更新的行；无新增 → 记录日志并跳过
        - history_df = query_recent(code, ktype, limit=300)
        - 拼接 history_df + new_df
        - merged_df = calc_indicators(merged, INDICATOR_CONFIG[ktype])
        - 只取新增行 → batch_upsert(code, ktype, new_rows)，日志打印新增根数
  3. Futu API 限频：每 30 秒 60 次，每个标的 3 次请求（1d+1w+4h），代码内留有余量
  4. 输出更新摘要
```

> **关键点**：增量更新时必须读出本地最近 **300 根**历史数据与新数据拼接后统一计算。MA250 回望 250 根、MA120 回望 120 根、RSI 预热 ~24 根、MACD 预热 ~60 根——只用 1 根新数据计算指标会严重偏差。
>
> ⚠️ **QFQ 复权断层坑**：provider 传了 `autype=QFQ`，但增量拉取只追加新数据；标的除权/拆股后历史价格基准变化，增量更新会留下"假暴跌"断层（典型：APH 2:1 拆股后 dd60 由 +1.3% 变 −49.3%）。修复需用 `scripts/refetch_klines.py` 全量重拉该标的。
>
> ⚠️ **盘中半截 K 线坑（已用代码兜住）**：增量过滤是 `date > last_date`（**严格大于**），写入后**永不覆盖**。在北京时间 21:30 后（= 美东盘中）运行 `update`，Futu 会返回当天进行中的那根；一旦落库，评分/温度/信号全部建立在未收盘数据上，且**再跑 `update` 也修不回来**（日志全是「无新增数据」），只能手工 `DELETE` 再重拉。现由 `market_clock.filter_closed_bars()` 在写入前拦截 —— 盘中跑会自然停在「上一个完整交易日」。需要强制写入时用 `update --allow-partial` 或 `TA_ALLOW_PARTIAL_BAR=1`。
> 实测对照（2026-10-16）：盘中快照 40.6 分 / 强买 22 只 → 收盘后 36.8 分 / 强买 33 只。
