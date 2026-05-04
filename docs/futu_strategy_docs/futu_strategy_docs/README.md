# TraderAnalysis 项目技术方案总览

> Futu 量化评分与模拟盘交易系统。基于 40 只核心观察标的，通过多指标加权评分自动触发模拟盘买入。采用三层架构：后端核心层 → 持久化存储层 → API 服务层。

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
├── __init__.py              # 版本号 0.2.0
├── __main__.py              # → cli:app
├── cli.py                   # CLI 入口（serve / init / update / run / temperature）
│
└── futu_strategy/           # 完整的三层架构代码
    │
    │── Part A: 后端核心层 ──────────────────────────
    ├── config.py             # 全局配置（从 data/watchlist.json 加载标的池）
    ├── providers.py          # OHLCV Schema + FutuLiveDataProvider + 数据归一化
    ├── data_fetcher.py       # 富途 K 线数据获取 + 额度预检
    ├── external_data.py      # 外部数据获取（VIX 快照、CNN F&G）
    ├── indicators.py         # 技术指标计算（纯函数，不感知标的/周期）
    ├── scorer.py             # 个股评分引擎（读指标值 → 判断 → 打分，9 项加权评分）
    ├── market_scorer.py      # 市场温度评分（6 维度加权，SPY/QQQ/GLD/VIXY）
    ├── trade_executor.py     # 模拟盘交易执行（限价单 + 持仓检查）
    │
    │── Part B: 持久化存储层 ────────────────────────
    ├── storage.py            # 数据库读写接口（所有 SQL 集中在此）
    ├── init_history.py       # 历史数据初始化（断点续传 + 频率控制）
    ├── daily_update.py       # 每日增量更新脚本
    │
    │── Part C: API 服务层 ──────────────────────────
    ├── api_server.py         # FastAPI 服务（只读查询 SQLite，供前端消费）
    │
    │── 公共 ───────────────────────────────────────
    ├── runner.py             # 主入口，串联全部模块
    ├── logger.py             # 日志与审计记录
    ├── __main__.py           # python -m trader_analysis.futu_strategy 入口
    └── __init__.py

data/
├── watchlist.json            # 40 只核心观察标的（JSON，含分类/标签/元信息）
└── indicators.db             # SQLite 数据库（gitignored，运行时自动生成）

logs/
├── score_log.jsonl           # 评分记录
└── trade_log.jsonl           # 交易记录
```

---

## 标的池管理

标的池通过 `data/watchlist.json` 统一管理，config.py 启动时自动加载并转换为 Futu 格式代码：

- **WATCHLIST**：`["US.QQQ", "US.SPY", ..., "US.MCD"]`（40 只，供 runner/init_history/daily_update 使用）
- **WATCHLIST_DETAIL**：带 name/category/tags/futu_code 的完整列表（供 API 返回前端）
- **WATCHLIST_CATEGORIES**：分类映射（如 `"mag7": "MAG7"`）

新增或删除标的只需编辑 `data/watchlist.json`，无需改代码。

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
│           ├─ [storage] 读本地最近 300 根
│           ├─ 拼接新旧数据
│           ├─ [indicators] calc_indicators()
│           └─ [storage] UPSERT 新增行
│
├─ 2. 运行策略评分（runner.py）
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
├─ GET /api/watchlist         → [api_server] → [config] → 完整标的池（含分类、标签、has_data 状态）
├─ GET /api/indicators?code=X → [api_server] → [storage] → K 线 + 指标 JSON（无数据返回 404 + 提示）
├─ GET /api/scores/latest     → [api_server] → [storage] → 最新评分（无数据返回 404 + 提示）
│
└─ 前端渲染：K 线图 + MA 叠加 + RSI 副图 + MACD 副图 + 评分面板
```

### 首次初始化流程

```
python -m trader_analysis init

│
├─ [storage] init_db() 建表
├─ 检查已有数据标的（自动跳过，支持断点续传）
├─ 检查 K 线额度（需 >= 待拉取标的数 × 2）
│
└─ for each code（3 秒间隔，避免触发频率限制）:
      ├─ [data_fetcher] 拉取 1000 根日线 + 200 根周线
      ├─ [indicators] calc_indicators() 计算全部历史指标
      └─ [storage] batch_upsert() 批量写入

可选参数：
  --codes US.AAPL US.TSLA    指定标的
  --force                     强制重新拉取
```

---

## 运行环境与依赖

### Python 版本
- Python 3.10+

### 依赖包

| 包 | 用途 | 所属层 |
|----|------|--------|
| `futu-api` | 富途 OpenAPI SDK | Part A |
| `pandas` | 数据处理 | 全局 |
| `numpy` | 数值计算 | 全局 |
| `scipy` | 背离检测（find_peaks） | Part A |
| `requests` | 外部 HTTP 请求（CNN F&G） | Part A |
| `fastapi` | API 服务框架 | Part C |
| `uvicorn` | ASGI 服务器 | Part C |
| `typer` | CLI 框架 | cli.py |

### 安装

```bash
# 核心依赖
pip install -e .

# 模拟盘策略额外依赖
pip install futu-api

# 开发依赖
pip install -e ".[dev]"
```

### 前提条件
- 富途 OpenD 运行在 `127.0.0.1:11111`
- 已登录富途账号，模拟账户可用
- 网络可访问 CNN F&G 接口（国内可能需要代理）

---

## CLI 命令

```bash
# 启动 API 服务
trader-analysis serve --host 0.0.0.0 --port 8000

# 启动 API 服务（开发模式，代码修改后自动重载）
uvicorn trader_analysis.futu_strategy.api_server:app --host 0.0.0.0 --port 8000 --reload --reload-dir src

# 历史数据初始化（断点续传，自动跳过已有数据）
trader-analysis init
trader-analysis init --codes US.AAPL --codes US.TSLA
trader-analysis init --force

# 每日增量更新
trader-analysis update

# 完整策略流程（增量更新 → 评分 → 交易）
trader-analysis run

# 市场温度评分（6 维度综合评分 + 目标仓位建议，从已入库数据计算，不需要 OpenD）
trader-analysis temperature
```

> **注意**：`data/indicators.db` 为纯本地文件（已加入 .gitignore），clone 后需重新运行 `trader-analysis init` 拉取数据。

---

## 异常处理策略

| 所属层 | 异常场景 | 处理方式 |
|--------|---------|---------|
| A 数据获取 | OpenD 连接失败 | 启动时检测，失败直接退出并提示 |
| A 数据获取 | 历史 K 线额度不足 | 打印警告，跳过本标的，继续下一个 |
| A 数据获取 | CNN F&G 接口超时/失败 | 该项得 0 分，继续评分，日志记录 |
| A 数据获取 | VIX 数据获取失败 | 该项得 0 分，继续评分 |
| A 指标计算 | 数据不足（K 线 < 250 根） | 跳过 MA250 指标，得 0 分 |
| A 指标计算 | MACD 背离检测谷底不足 2 个 | 返回 False，继续评分 |
| A 交易执行 | 模拟账户购买力不足 | 捕获错误，写日志，不中断 |
| A 交易执行 | 重复买入 | 下单前查持仓，已持有且非 STRONG_BUY 则跳过 |
| B 存储层 | 数据库文件不存在 | `init_db()` 自动建表 |
| B 存储层 | UPSERT 冲突 | `INSERT OR REPLACE` 自动覆盖旧数据 |
| B 初始化 | 中途失败 | 断点续传，重新运行自动跳过已完成标的 |
| C API 层 | 查询的标的无数据 | 返回 HTTP 404 + 描述性提示信息 |

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

### MA250 数据量
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

- **纯计算约束**：`indicators.py` 不依赖 I/O，只接收 DataFrame，保证可独立测试。
- **统一数据归一化**：所有数据源（富途 API）必须通过 `providers.py` 的 `normalize_ohlcv()` 处理后才能进入计算层。
- **SQL 集中**：所有 SQL 集中在 `storage.py`，其他模块不直接写 SQL。
- **OpenD 隔离**：`providers.py` 的 `FutuLiveDataProvider` 是唯一依赖 `futu-api` 的数据层模块。
- **连接复用**：`OpenQuoteContext` 和 `OpenSecTradeContext` 在循环外创建，循环结束后统一关闭，禁止在循环内重建。
- **文档同步**：每次结构性变更后，必须在同一次提交中更新本文件。

---

*文档版本：v2.1 | 最后更新：2026-04-23*
*适用环境：富途 OpenAPI + Python 3.10+ | 交易环境：模拟盘（SIMULATE）*
