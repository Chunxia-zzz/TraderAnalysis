# TraderAnalysis 项目技术方案总览

> 量化分析平台，提供两条并行路径：**HTTP API 服务**（实时指标查询）和**模拟盘策略**（多指标评分 → 自动买入）。两条路径共享同一套数据层与指标计算层。模拟盘策略（futu_strategy）采用 v2.0 三层架构：后端核心层 → 持久化存储层 → API 服务层。

---

## v1.0 → v2.0 变更指引

> **给开发者 / AI 的迁移说明**：v2.0 在 v1.0 基础上新增了持久化存储层（Part B）和 API 服务层（Part C），并对部分已有模块进行了重构。请先读完本节，再对照项目现有代码进行修改。

### 已有文件（v1.0 已实现，需改造）

| 文件 | 改造要点 | 详细方案 |
|------|---------|---------|
| `indicators.py` | 重构为通用函数 `calc_indicators(df, config)`，去掉判断逻辑，判断全部移到 `scorer.py` | [part_a_indicators.md](part_a_indicators.md) |
| `scorer.py` | 承接原 indicators 中的阈值判断（`RSI < 30` 等），从 DataFrame 读指标值做评分 | [part_a_scorer.md](part_a_scorer.md) |
| `config.py` | 新增 `DAILY/WEEKLY_INDICATOR_CONFIG`、`DB_PATH`、`WATCHLIST`，原有配置保持不变 | 各模块文档中均有涉及 |
| `strategy_runner.py` | 改为先调 `daily_update.py` 更新存储层，再从 `storage.py` 读已计算好的指标传给 `scorer.py` | 见本文流程图 |

### 新增文件（v2.0 新增，从零创建）

| 文件 | 说明 | 详细方案 |
|------|------|---------|
| `storage.py` | 数据库读写接口，所有 SQL 集中在此 | [part_b_storage.md](part_b_storage.md) |
| `init_history.py` | 一次性历史数据初始化脚本 | [part_b_storage.md](part_b_storage.md) |
| `daily_update.py` | 每日定时增量更新脚本 | [part_b_storage.md](part_b_storage.md) |
| `api_server.py` | FastAPI 服务，只读查询 SQLite，供前端消费 | [part_c_api.md](part_c_api.md) |
| `data/indicators.db` | SQLite 数据库文件（运行 init_history 后自动生成） | [part_b_storage.md](part_b_storage.md) |

### 无需改动的文件

| 文件 | 说明 |
|------|------|
| `data_fetcher.py` | K 线获取逻辑不变，继续作为数据源供 init_history / daily_update 调用 |
| `external_data.py` | VIX / CNN F&G 获取逻辑不变 |
| `trade_executor.py` | 交易执行逻辑不变 |
| `logger.py` | 日志写入逻辑不变 |

### 建议改造顺序

```
1. 新建 storage.py          → 读 part_b_storage.md
2. 新建 init_history.py     → 读 part_b_storage.md → 运行一次，确认数据入库
3. 新建 daily_update.py     → 读 part_b_storage.md → 模拟运行，确认增量更新
4. 改造 indicators.py       → 读 part_a_indicators.md
5. 改造 scorer.py           → 读 part_a_scorer.md
6. 改造 config.py           → 读各模块文档中的配置项说明
7. 改造 strategy_runner.py  → 读本文流程图
8. 新建 api_server.py       → 读 part_c_api.md → 启动验证接口返回
```

> **操作前请先读取项目目录和现有代码**，对照上表确认每个文件的实际状态，再动手修改。

---

## 三层架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                     Part A — 后端核心层                               │
│                                                                      │
│   负责：拉取外部数据、计算指标、评分、交易执行、定时调度               │
│   依赖：Futu OpenD、外部 HTTP 接口                                   │
│                                                                      │
│   ┌─────────────┐  ┌─────────────┐  ┌──────────┐  ┌──────────────┐  │
│   │ data_fetcher│→ │ indicators  │→ │ scorer   │→ │trade_executor│  │
│   │ external_   │  │             │  │          │  │              │  │
│   │ data        │  │             │  │          │  │              │  │
│   └─────────────┘  └─────────────┘  └──────────┘  └──────────────┘  │
└──────────────┬────────────────────────────────────────────┬──────────┘
               │ 写入（指标数据、评分结果）                   │
               ▼                                            │
┌──────────────────────────────────────────────────────┐    │
│                Part B — 持久化存储层                    │    │
│                                                      │    │
│   负责：K 线 + 指标的本地存储、历史初始化、增量更新      │    │
│   实现：SQLite（indicators.db）+ JSONL（日志）          │    │
│   接口：storage.py（read / write / upsert）            │    │
└───────────────┬──────────────────────────────────────┘    │
                │ 读取（已存储的指标数据）                     │
                ▼                                            │
┌──────────────────────────────────────────────────────┐    │
│                Part C — API 服务层                      │    │
│                                                      │    │
│   负责：将存储层数据暴露为 HTTP 接口，供前端消费        │    │
│   实现：FastAPI + SQLite 只读查询                      │    │
│   特点：无需连接 Futu OpenD，独立运行                   │    │
└──────────────────────────────────────────────────────┘
```

**三层解耦的意义：**

| 特性 | 说明 |
|------|------|
| 后端可独立运行 | 即使没有前端，策略照常定时评分和交易 |
| API 层可独立运行 | 只要数据库有数据，不依赖 Futu OpenD |
| 存储层是桥梁 | 后端写、API 读，通过 SQLite 文件解耦 |
| 可独立替换 | 换数据源只改 Part A，B 和 C 不变 |

---

## 项目文件结构

```
src/trader_analysis/
│
├── data/                              共享数据层
│   ├── schemas.py                     OHLCV 标准 schema（8 个字段，统一小写）
│   └── providers.py                   FutuLiveDataProvider（实时）
│                                      CSVDataProvider / ParquetDataProvider（回测/开发）
│                                      normalize_ohlcv()（所有数据源的统一归一化入口）
│
├── indicators/                        共享指标层
│   ├── base.py                        IndicatorSpec / IndicatorRegistry / apply_indicators
│   ├── builtins.py                    ── 统一指标入口 ──
│   │                                  calc_rsi / calc_macd_hist / calc_bb_lower / calc_sma
│   │                                  （供评分系统和其他直接调用场景使用）
│   │                                  ── IndicatorSpec 工厂 ──
│   │                                  sma / ema / rsi / macd / atr / bbands
│   │                                  （供 Strategy pipeline 使用）
│   └── __init__.py
│
├── signals/                           信号层
│   ├── types.py                       Signal / SignalSet / SignalType（BUY/SELL/HOLD）
│   └── rules.py                       MovingAverageCrossRule / RSIReversalRule
│
├── strategy/                          策略层
│   ├── strategy.py                    Strategy（enrich → generate_signals）
│   └── examples.py                    ma_cross / rsi_reversal 示例策略
│
├── backtest/                          回测层
│   ├── engine.py                      回测引擎
│   └── report.py                      Sharpe / 最大回撤 / 胜率报告
│
├── api/                               HTTP API 服务（路径一）
│   ├── service.py                     IndicatorService（多 symbol 缓存 + 定时刷新）
│   └── app.py                         FastAPI 路由（/health /v1/indicators/* /v1/signals/*）
│
├── futu_strategy/                     模拟盘策略子包（路径二，v2.0 三层架构）
│   │
│   │── Part A: 后端核心层 ──────────────────────────
│   ├── config.py                      全局配置（标的列表、指标参数、仓位、阈值、日志路径等）
│   ├── runner.py                      主入口，串联 A 层所有模块
│   ├── data_fetcher.py                富途 K 线数据获取（日线 250 根 + 周线 60 根）+ 额度预检
│   ├── external_data.py               外部数据获取（VIX 快照、CNN F&G）
│   ├── indicators.py                  技术指标计算（纯函数，不感知标的/周期）
│   ├── scorer.py                      评分引擎（读指标值 → 判断 → 打分，9 项加权评分）
│   ├── trade_executor.py              模拟盘交易执行（限价单 + 持仓检查）
│   │
│   │── Part B: 持久化存储层 ────────────────────────
│   ├── storage.py                     数据库读写接口（所有 SQL 集中在此）
│   ├── init_history.py                一次性历史数据初始化脚本
│   ├── daily_update.py                每日定时增量更新脚本
│   ├── data/
│   │   └── indicators.db              SQLite 数据库文件
│   │
│   │── Part C: API 服务层 ──────────────────────────
│   ├── api_server.py                  FastAPI 服务（只读查询 SQLite，供前端消费）
│   │
│   │── 公共 ───────────────────────────────────────
│   ├── logger.py                      日志与审计记录
│   ├── __main__.py                    python -m trader_analysis.futu_strategy 入口
│   ├── __init__.py
│   └── logs/
│       ├── score_log.jsonl            评分记录
│       └── trade_log.jsonl            交易记录
│
├── notify/                            通知模块
│   └── wecom.py                       企业微信通知（框架已有，待接入实时路径）
│
├── cli.py                             typer CLI 入口
├── __main__.py
└── __init__.py
```

---

## 模块索引

| 模块 | 文档 | 一句话摘要 |
|------|------|-----------|
| 数据获取 | [part_a_data_fetcher.md](part_a_data_fetcher.md) | 从 Futu API 拉 K 线，从外部接口获取 VIX / CNN F&G |
| 指标计算 | [part_a_indicators.md](part_a_indicators.md) | 通用函数 `calc_indicators(df, config)`，不感知标的/周期，只追加数值列 |
| 评分系统 | [part_a_scorer.md](part_a_scorer.md) | 读取指标值做阈值判断，9 项加权评分，输出 0~100 分 + 信号 |
| 交易执行 | [part_a_trade_executor.md](part_a_trade_executor.md) | 根据评分信号执行模拟盘买入，含仓位规则和调度机制 |
| 持久化存储 | [part_b_storage.md](part_b_storage.md) | SQLite 数据库设计、storage.py 接口、初始化和增量更新脚本 |
| API 服务 | [part_c_api.md](part_c_api.md) | FastAPI 接口设计、响应格式、前端图表集成建议 |

---

## 共享层说明

以下模块位于 `src/trader_analysis/` 顶层，被 HTTP API 服务和模拟盘策略两条路径共享。

### 数据层（`data/`）

#### OHLCV 标准 Schema

所有数据源输出必须经过 `normalize_ohlcv()` 归一化：

| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp` | datetime | K 线时间 |
| `open / high / low / close` | float | 价格（前复权 QFQ） |
| `volume` | float | 成交量 |
| `symbol` | str | 标的代码，如 `US.AAPL` |
| `timeframe` | str | 周期，如 `1D` / `1W` |

#### 数据源

| 类 | 用途 |
|----|------|
| `FutuLiveDataProvider` | 生产环境，通过 `OpenQuoteContext.request_history_kline` 实时拉取 |
| `CSVDataProvider` | 开发 / 回测，读取本地 CSV 文件 |
| `FutuJsonDataProvider` | 读取富途 API 脚本导出的 JSON 文件 |

### 指标层（`indicators/`）

`indicators/builtins.py` 是所有指标计算的**唯一入口**，分两套接口：

#### calc_* 独立函数（直接返回 Series）

用于模拟盘策略评分、临时计算等场景：

```python
from trader_analysis.indicators import calc_rsi, calc_macd_hist, calc_bb_lower, calc_sma

rsi_series   = calc_rsi(close, period=14)
hist_series  = calc_macd_hist(close, fast=12, slow=26, signal=9)
lower_series = calc_bb_lower(close, period=20, std_mult=2.0)
ma200_series = calc_sma(close, period=200)
```

#### IndicatorSpec 工厂（流水线风格）

用于 `Strategy` / `Backtest` pipeline，接受并返回完整 DataFrame：

```python
from trader_analysis.indicators import rsi, macd, bbands

strategy = Strategy(
    name="my_strategy",
    indicators=[rsi(14), macd(), bbands()],
    rule=RSIReversalRule(rsi_col="rsi_14"),
)
enriched_df = strategy.enrich(df)
```

### 信号层（`signals/`）

- `types.py`：`Signal` / `SignalSet` / `SignalType`（BUY / SELL / HOLD）
- `rules.py`：`MovingAverageCrossRule` / `RSIReversalRule`

### 策略层（`strategy/`）

- `strategy.py`：`Strategy` 类（enrich → generate_signals 流水线）
- `examples.py`：`ma_cross` / `rsi_reversal` 示例策略

### 回测层（`backtest/`）

- `engine.py`：回测引擎
- `report.py`：Sharpe / 最大回撤 / 胜率报告

### HTTP API 服务（`api/`）

```bash
# 启动（通过环境变量配置数据源）
TA_DATA_PATH=examples/mock_futu_kline_HK.00700.json uvicorn trader_analysis.api.app:app

# 主要接口
GET /health
GET /v1/indicators/latest
GET /v1/indicators/history?limit=100
GET /v1/indicators/ma?timeframe=1D&period=200
GET /v1/signals/latest
```

### 通知模块（`notify/`）

- `wecom.py`：企业微信通知（框架已有，待接入实时路径）

### CLI 入口（`cli.py`）

基于 typer 的命令行入口，统一启动 API 服务和策略运行等操作。

---

## 完整执行流程图

### 每日定时执行流程（主流程）

```
定时触发（每日收盘后）
│
├─ 1. 增量更新存储层（daily_update.py）
│     │
│     └─ for each code in watchlist:
│           ├─ [storage] 查本地最新日期
│           ├─ [data_fetcher] 拉取新增 K 线（日线 + 周线）
│           ├─ [storage] 读本地最近 250 根
│           ├─ 拼接新旧数据
│           ├─ [indicators] calc_indicators()
│           └─ [storage] UPSERT 新增行
│
├─ 2. 运行策略评分（strategy_runner.py）
│     │
│     ├─ 创建 OpenQuoteContext + OpenSecTradeContext（复用）
│     ├─ 获取模拟账户 acc_id
│     ├─ [external_data] 获取 VIX（一次）
│     ├─ [external_data] 获取 CNN F&G（一次）
│     │
│     └─ for each code in watchlist:
│           ├─ [storage] 读取日线指标 DataFrame
│           ├─ [storage] 读取周线指标 DataFrame
│           │
│           ├─ [scorer] 汇总评分：
│           │     ├─ 读 rsi14, dif, dea, macd, boll_lower, ma120, ma250, vol_ma20
│           │     ├─ detect_macd_divergence()
│           │     ├─ detect_panic_volume()
│           │     └─ 加入 VIX + CNN F&G → total_score, signal
│           │
│           ├─ [storage] 写入评分结果
│           ├─ [logger] 写评分日志
│           │
│           ├─ if signal in ["BUY", "STRONG_BUY"]:
│           │     ├─ [trade_executor] 获取快照价格
│           │     ├─ 计算买入数量
│           │     ├─ 查持仓（refresh_cache=True）
│           │     ├─ place_order（SIMULATE）
│           │     └─ [logger] 写交易日志
│           │
│           └─ 下一个标的
│
└─ 3. 关闭连接
```

### 前端查询流程（独立于主流程）

```
用户打开前端页面
│
├─ GET /api/watchlist         → [api_server] → [storage] → 标的列表
├─ GET /api/indicators?code=X → [api_server] → [storage] → K 线 + 指标 JSON
├─ GET /api/scores/latest     → [api_server] → [storage] → 最新评分
│
└─ 前端渲染：K 线图 + MA 叠加 + RSI 副图 + MACD 副图 + 评分面板
```

### 首次初始化流程（仅运行一次）

```
python init_history.py --codes HK.00700 US.AAPL SH.600519
│
├─ [storage] init_db() 建表
├─ 检查 K 线额度（需 >= 标的数 × 2）
│
└─ for each code:
      ├─ [data_fetcher] 拉取 1000 根日线 + 200 根周线（初始化取上限）
      ├─ [indicators] calc_indicators() 计算全部历史指标
      └─ [storage] batch_upsert() 批量写入
```

---

## 运行环境与依赖

### Python 版本
- Python 3.8+

### 依赖包

| 包 | 用途 | 所属层 |
|----|------|--------|
| `futu-api` | 富途 OpenAPI SDK | 共享层 / futu_strategy Part A |
| `pandas` | 数据处理 | 全局 |
| `numpy` | 数值计算 | 全局 |
| `pandas-ta` | 技术指标计算 | futu_strategy Part A |
| `scipy` | 背离检测（find_peaks） | futu_strategy Part A |
| `requests` | 外部 HTTP 请求（CNN F&G） | futu_strategy Part A |
| `schedule` | 定时调度（可选，也可用系统 cron） | futu_strategy Part A |
| `fastapi` | API 服务框架 | api / futu_strategy Part C |
| `uvicorn` | ASGI 服务器 | api / futu_strategy Part C |
| `typer` | CLI 框架 | cli.py |
| `pyarrow` | Parquet 数据支持（可选） | 共享层 data |

### 安装

```bash
# 核心依赖（pyproject.toml 已声明）
pip install -e .

# 模拟盘策略额外依赖
pip install futu-api scipy requests pandas-ta schedule

# 回测 Parquet 支持（可选）
pip install -e ".[parquet]"

# futu_strategy 完整依赖
pip install futu-api pandas numpy pandas-ta scipy requests schedule fastapi uvicorn
```

### 前提条件
- 富途 OpenD 运行在 `127.0.0.1:11111`（共享层 `FutuLiveDataProvider` 和 futu_strategy Part A 需要）
- 已登录富途账号，模拟账户可用
- 网络可访问 CNN F&G 接口（国内可能需要代理）

---

## 异常处理策略

| 所属层 | 异常场景 | 处理方式 |
|--------|---------|---------|
| A 数据获取 | OpenD 连接失败 | 启动时检测，失败直接退出并提示 |
| A 数据获取 | 历史 K 线额度不足 | 打印警告，跳过本标的，继续下一个 |
| A 数据获取 | CNN F&G 接口超时/失败 | 该项得 0 分，继续评分，日志记录 `fg_score: null` |
| A 数据获取 | VIX 数据获取失败 | 该项得 0 分，继续评分 |
| A 指标计算 | 数据不足（K 线 < 250 根） | 跳过 MA250 指标，得 0 分 |
| A 指标计算 | MACD 背离检测谷底不足 2 个 | 返回 False，继续评分 |
| A 交易执行 | 模拟账户购买力不足 | 捕获错误，写日志，不中断 |
| A 交易执行 | 重复买入 | 下单前查持仓，已持有且非 STRONG_BUY 则跳过 |
| B 存储层 | 数据库文件不存在 | `init_db()` 自动建表 |
| B 存储层 | UPSERT 冲突 | `INSERT OR REPLACE` 自动覆盖旧数据 |
| C API 层 | 查询的标的不在库中 | 返回空数组 `{"data": []}` |

---

## 日志与审计

由 `logger.py` 实现，所有评分和交易记录写入 JSONL 文件（每行一条 JSON）。

**评分日志（`logs/score_log.jsonl`）：**
```json
{"timestamp": "2026-04-13 06:01:23", "code": "US.AAPL", "total_score": 82, "signal": "BUY", "breakdown": {}}
```

**交易日志（`logs/trade_log.jsonl`）：**
```json
{"timestamp": "2026-04-13 06:01:25", "code": "US.AAPL", "signal": "BUY", "score": 82, "qty": 6, "price": 168.5, "order_id": "7890123", "trd_env": "SIMULATE", "status": "success"}
```

---

## 关键实现细节

### 连接复用
不要在循环内反复创建/关闭 OpenD 连接，会导致超时。循环外创建，循环结束后关闭。

### K 线额度检查
每次运行前检查一次，确认 `remain_count >= 标的数 × 2`。

### MA200 数据量
MA250 需要至少 250 根预热。初始化时拉取 1000 根（API 单次上限），增量更新时从本地读 300 根拼接即可。

### 增量更新的拼接逻辑
不能只用新的 1 根 K 线计算指标。MA120/MA250/RSI/MACD 有回望期，需从本地库读出最近 300 根，拼接新数据后统一计算，再将新行写回库。

### VIX 和 CNN F&G 全局共用
两者是市场级数据（与个股无关），同一次运行只获取一次，模块级缓存复用。

### 模拟账户 acc_id
运行开始时调用一次 `get_acc_list()`，过滤 `trd_env == 'SIMULATE'`，取第一个 `acc_id`，后续复用。

### `refresh_cache=True`
STOCK_AND_OPTION 类型模拟账户查询持仓/资金时必须传此参数，否则可能导致重复买入。

---

## 关键约定

- **纯计算约束**：`indicators/`、`signals/`、`backtest/` 不依赖 I/O，只接收 DataFrame，保证单元测试和回测可独立运行。
- **统一数据归一化**：所有数据源（富途 API / CSV / JSON）必须通过 `normalize_ohlcv()` 处理后才能进入计算层。
- **统一指标入口**：所有指标数学逻辑只写一遍（`builtins.py` 内的 `_*_s` helpers），`calc_*` 函数和 `IndicatorSpec` 工厂均调用同一套实现，不重复代码。
- **OpenD 隔离**：`FutuLiveDataProvider` 是唯一依赖 `futu-api` 的 data 层模块；开发/测试环境用 `CSVDataProvider` 替代。
- **连接复用**：`OpenQuoteContext` 和 `OpenSecTradeContext` 在循环外创建，循环结束后统一关闭，禁止在循环内重建。
- **文档同步**：每次结构性变更（新增模块、接口变更、数据流调整）后，必须在同一次提交中更新本文件。

---

*文档版本：v2.0 | 最后更新：2026-04-20*
*适用环境：富途 OpenAPI + Python 3.8+ | 交易环境：模拟盘（SIMULATE）*
