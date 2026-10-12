# TraderAnalysis 项目技术方案总览

> ⚠️ **本文档是 2026-05 的历史设计稿（v2.3），部分内容已与当前代码不符。**
> **现状请以根目录 [`README.md`](../../../README.md) 与 [`docs/api.md`](../../api.md) 为准。**
>
> 2026-10-12 全量审计已就地更正的项（见文中 `⚠️ 勘误` 标注）：
> 标的池数据源与数量、Part D 认证层（已删除）、`external_data.py`（不存在）、
> 评分维度数（9 → 6）、API 层"只读且不依赖 OpenD"（实为 8 个写端点 + 4 个依赖 OpenD）、
> 无数据返回码（404 → HTTP 200）、VIX / CNN F&G（已不参与评分）、重复买入规则。
>
> 仍**未逐句重写**的部分：流程图与部分散文描述仍保留当时的形态，**不要据此判断现状**。

> Futu 量化评分与模拟盘交易系统。基于 **195 只**观察标的（存 SQLite `watchlist` 表），
> 通过 **6 因子**连续映射评分自动触发模拟盘买入。采用三层架构：后端核心层 → 持久化存储层 → API 服务层。

---

## 三层架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                     Part A — 后端核心层                               │
│                                                                      │
│   负责：拉取外部数据、计算指标、评分、交易执行、定时调度               │
│   依赖：Futu OpenD                                                   │
│                                                                      │
│   ┌─────────────┐  ┌─────────────┐  ┌──────────┐  ┌──────────────┐  │
│   │ data_fetcher│→ │ indicators  │→ │ scorer   │→ │trade_executor│  │
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
│   实现：FastAPI + SQLite 查询                          │    │
│   特点：**大部分端点**无需 Futu OpenD                   │    │
└──────────────────────────────────────────────────────┘
```

> ⚠️ **勘误（2026-10-12）**：
> ① Part A 图中的 `external_data`（VIX / CNN F&G）**模块已不存在**，评分也不再用这两项数据。
> ② Part C 此前写「FastAPI + SQLite **只读**查询 / **无需**连接 Futu OpenD，独立运行」——
> 实测 `api_server.py` 有 **8 个写端点**（`POST/PUT/PATCH/DELETE`），
> 且 `GET /api/position`、`GET /api/allocation`、`POST /api/watchlist`、`POST /api/watchlist/refresh-snapshot`
> **4 个端点会直连 OpenD**。准确说法是「**评分/指标/信号那一大类**可脱离 OpenD 运行」。

**三层解耦的意义：**

| 特性 | 说明 |
|------|------|
| 后端可独立运行 | 即使没有前端，策略照常定时评分和交易 |
| API 层基本可独立运行 | 只要数据库有数据，评分/指标/信号类端点不依赖 Futu OpenD（4 个例外见上） |
| 存储层是桥梁 | 后端写、API 读，通过 SQLite 文件解耦 |
| 可独立替换 | 换数据源只改 Part A，B 和 C 不变 |

---

## 项目文件结构

```
src/trader_analysis/
├── __init__.py              # 版本号 0.2.0
├── __main__.py              # → cli:app
├── cli.py                   # CLI 入口（18 个命令，见「CLI 命令」节）
│
└── futu_strategy/           # 完整的三层架构代码
    │
    │── Part A: 后端核心层 ──────────────────────────
    ├── config.py             # 全局配置（标的池从 SQLite watchlist 表动态读取，JSON 仅作回退）
    ├── providers.py          # OHLCV Schema + FutuLiveDataProvider + 数据归一化
    ├── data_fetcher.py       # 富途 K 线数据获取 + 额度预检
    ├── indicators.py         # 技术指标计算（纯函数，不感知标的/周期）
    ├── scorer.py             # 个股评分引擎（6 因子连续映射，满分 100）
    ├── market_scorer.py      # 市场温度评分（3 维度加权，SPY/QQQ）+ 资产温度（GLD/BTC）
    ├── technical_analysis.py # 道氏三层趋势 + 支撑/压力（Swing Pivot 聚类）+ 盈亏比
    ├── top_detector.py       # 顶部信号检测
    ├── bottom_detector.py    # 底部信号检测
    ├── ema_cross_detector.py # EMA5/30 交叉检测
    ├── livermore_detector.py # 利弗莫尔关键点（独立信号体系，2026-10-12 新增）
    ├── trade_executor.py     # 模拟盘交易执行（限价单 + 持仓检查）
    ├── sell_executor.py      # 卖出执行
    ├── sell_advisor.py       # 卖出建议
    ├── tp_sl.py              # 止盈止损计算
    ├── backtest.py           # 信号回测（5 种模式）
    ├── position_fetcher.py   # 实时持仓查询（需 OpenD）
    ├── allocation.py         # 目标仓位配置与偏离/加仓建议
    ├── content_generator.py  # 自媒体文案生成
    ├── review_generator.py   # 日/周复盘报告
    ├── template_store.py     # 文案模板存储
    ├── grid_trader/          # 网格交易引擎（子包）
    │
    │── Part B: 持久化存储层 ────────────────────────
    ├── storage.py            # 数据库读写接口（所有 SQL 集中在此）
    ├── init_history.py       # 历史数据初始化（断点续传 + 频率控制）
    ├── daily_update.py       # 每日增量更新脚本
    │
    │── Part C: API 服务层 ──────────────────────────
    ├── api_server.py         # FastAPI 服务（38 个路由，含 8 个写端点）
    │
    │── ❌ Part D: 认证层 —— 已彻底移除 ──────────────
    │   （auth.py / auth_storage.py 于 v2.8+ 从仓库删除；cli.py 的 create-admin 因此断链）
    │
    │── Part E: 标的池管理 ──────────────────────────
    ├── watchlist_storage.py  # watchlist 表 CRUD + 迁移
    ├── stock_info_fetcher.py # 富途选股/信息填充接口（search_stocks 已实现但无路由调用）
    │
    │── Part F: 基本面分析 ──────────────────────────
    ├── fundamental_fetcher.py # yfinance 数据批量采集
    ├── fundamental_scorer.py  # 5 因子基本面评分引擎（不并入 total_score）
    │
    │── 公共 ───────────────────────────────────────
    ├── runner.py             # 主入口，串联全部模块
    ├── logger.py             # 日志与审计记录（JSONL）
    ├── stock_names.py        # 代码 → 名称映射
    ├── position_state.py     # 持仓状态机
    ├── __main__.py           # python -m trader_analysis.futu_strategy 入口
    └── __init__.py

scripts/                      # 运维脚本
├── audit_morningstar.py      # 晨星公允价值全量核对
├── fetch_fundamental_targets.py  # 分析师共识目标价抓取
├── refetch_klines.py         # 单标的 K 线重拉（修复复权断层）
└── backfill_klines.py        # K 线回填

data/
├── watchlist.json            # 49 条回退列表（表为空时才用；**不是**主数据源）
├── target_allocation.json    # 永久组合目标配置（页面可编辑，故意不入库）
└── indicators.db             # SQLite 数据库（gitignored，运行时自动生成）

logs/
├── score_log.jsonl           # 评分记录
└── trade_log.jsonl           # 交易记录
```

> ⚠️ **勘误（2026-10-12）**：此文件树此前列出 `external_data.py`（VIX/CNN F&G）与 **Part D 认证层**
> （`auth.py` / `auth_storage.py`）三个文件，**它们在仓库中均不存在**；
> 同时还漏列了上表中的 `technical_analysis.py`、四个检测器、`livermore_detector.py`、
> `sell_*` / `tp_sl` / `backtest` / `position_fetcher` / `allocation` / `content_*` / `review_*` /
> `template_store` / `grid_trader/` / `stock_names` / `position_state` 等模块，已补齐。
> `scripts/` 与 `data/target_allocation.json` 也一并补入。

---

## 标的池管理

> ⚠️ **勘误（2026-10-12）**：本节此前写「标的池通过 `data/watchlist.json` 统一管理…新增或删除标的只需编辑 json，无需改代码」——
> **这个说法已过时**。标的主数据源现在是 **SQLite `watchlist` 表**（195 行，26 个分类），
> 通过标的管理页或 `POST/PATCH/DELETE /api/watchlist` 增删改；
> `data/watchlist.json`（49 条）**只在表为空时作回退**。

标的池由 SQLite `watchlist` 表管理，`config.py` 通过**动态属性**暴露（每次访问都查库，所以改完无需重启）：

- **WATCHLIST**：`["US.QQQ", "US.SPY", ..., "US.MCD"]`（当前 195 只，供 runner/init_history/daily_update 使用）
- **WATCHLIST_DETAIL**：带 name/category/tags/futu_code 的完整列表（供 API 返回前端）
- **WATCHLIST_CATEGORIES**：分类映射（如 `"mag7": "MAG7"`）

```python
# config.py 实际实现（简化）
def get_watchlist() -> list[str]:
    if watchlist_count() > 0:          # 表非空 → 用 DB
        return get_all_codes()
    return _WATCHLIST_FROM_JSON        # 表空 → 回退 JSON
```

新增或删除标的：走 API / 管理页；**改完必须跑 `init` 拉历史数据**，`score` / `scan-signals` 才会纳入。

---

## 模块索引

| 模块 | 文档 | 一句话摘要 |
|------|------|-----------|
| 数据获取 | [part_a_data_fetcher.md](part_a_data_fetcher.md) | 从 Futu API 拉 K 线 |
| 指标计算 | [part_a_indicators.md](part_a_indicators.md) | 通用函数 `calc_indicators(df, config)`，不感知标的/周期，只追加数值列 |
| 评分系统 | [part_a_scorer.md](part_a_scorer.md) | **6 因子连续映射**，输出 0~100 分 + 信号（阈值 80 / 60） |
| 交易执行 | [part_a_trade_executor.md](part_a_trade_executor.md) | 根据评分信号执行模拟盘买入，含仓位规则和调度机制 |
| 持久化存储 | [part_b_storage.md](part_b_storage.md) | SQLite 数据库设计、storage.py 接口、初始化和增量更新脚本 |
| API 服务 | [part_c_api.md](part_c_api.md) | ⚠️ **v2.0 初始设计稿，已过期** —— 现状请看 [`docs/api.md`](../../api.md) |
| 标的池管理 | [part_e_watchlist_management.md](part_e_watchlist_management.md) | watchlist 表结构、CRUD API、导入流程 |
| 基本面分析 | [part_f_fundamental.md](part_f_fundamental.md) | yfinance 采集 + 5 因子基本面评分 |
| 仓位策略 | [position-sizing-strategy.md](position-sizing-strategy.md) | ⚠️ **含大量已废弃的 6 维度 / VIX 内容**，现状见 `market_scorer.py` |

> ⚠️ **勘误（2026-10-12）**：① 指标/评分两行的「9 项加权评分」已改为 **6 因子**；
> ② 此前缺失的 part_e / part_f / position-sizing 三份文档已补入索引；
> ③ `CHANGELOG.md` 中曾引用 `part_d_auth.md`，**该文件不存在**（认证层已删除），勿再引用。---

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
│     │
│     └─ for each code in watchlist:
│           ├─ [storage] 读取日线指标 DataFrame
│           ├─ [storage] 读取周线指标 DataFrame
│           │
│           ├─ [scorer] 6 因子连续映射评分 → total_score, signal：
│           │     ├─ C1 周线 RSI6        (20) (80 - rsi) / 60
│           │     ├─ C2 日线 MACD 百分位 (20) 1 - percentile_rank(252)
│           │     ├─ C3 布林带 %B        (15) 1 - %B
│           │     ├─ C4 日线 RSI6        (20) (80 - rsi) / 60
│           │     ├─ C5 周线 MACD 百分位 (10) 1 - percentile_rank(52)
│           │     ├─ C6 60 日回撤        (15) (drawdown - 0.05) / 0.20
│           │     └─ 大盘温度加成：composite < 40 时最多 +15
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

> ⚠️ **勘误（2026-10-12）**：此流程图此前写「[external_data] 获取 VIX / CNN F&G」「读 `rsi14`」「`detect_macd_divergence()`」
> 「加入 VIX + CNN F&G」——**这四项都已不在评分路径上**：
> 评分现为 **6 因子**（上列 C1~C6），不含 VIX / CNN F&G / 背离检测；
> 指标列是 `rsi6 / rsi12 / rsi24`（**没有 `rsi14`**）；`detect_macd_divergence()` 虽仍在 `indicators.py` 中定义，但 `scorer.py` 未调用。

### 前端查询流程（独立于主流程）

```
用户打开前端页面
│
├─ GET /api/watchlist         → [api_server] → [watchlist_storage] → 完整标的池（含分类、标签、晨星折价）
├─ GET /api/indicators?code=X → [api_server] → [storage] → K 线 + 指标 JSON（无数据返回 HTTP 200 + data:null）
├─ GET /api/scores/latest     → [api_server] → [storage] → 最新评分（无数据返回 HTTP 200 + data:null）
│
└─ 前端渲染：K 线图 + MA 叠加 + RSI 副图 + MACD 副图 + 评分面板
```

> ⚠️ **勘误（2026-10-12）**：此前写「无数据返回 **404** + 提示」——现统一为 **HTTP 200 + `{data: null, message}`**（v2.3 起）。
> `GET /api/watchlist` 也已不再经 `config` 而是直接读 `watchlist` 表。

### 首次初始化流程

```
python -m trader_analysis init
     （或等价地：trader-analysis init）

│
├─ [storage] init_db() 建表
├─ 检查已有数据标的（自动跳过，支持断点续传）
├─ 检查 K 线额度（需 >= 待拉取标的数 × 2）
│
└─ for each code（3 秒间隔，避免触发频率限制）:
      ├─ [data_fetcher] 拉取 1000 根日线 + 200 根周线
      │   （= config.INIT_DAILY_KLINE_COUNT / INIT_WEEKLY_KLINE_COUNT）
      ├─ [indicators] calc_indicators() 计算全部历史指标
      └─ [storage] batch_upsert() 批量写入

可选参数：
  --codes US.AAPL US.TSLA    指定标的（注意：CLI 是 list 选项，可重复传）
  --force                     强制重新拉取
  --start 2022-06-01          指定起始日期，拉取更长历史
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
| `scipy` | 技术分析辅助（`indicators.py`，与评分路径无关） | Part A |
| `fastapi` | API 服务框架 | Part C |
| `uvicorn` | ASGI 服务器 | Part C |
| `typer` | CLI 框架 | cli.py |

> ⚠️ **勘误（2026-10-12）**：① `scipy` 此前标注为「背离检测（find_peaks）」—— 背离检测已不在评分路径上；
> ② `requests` 此前标注为「外部 HTTP 请求（CNN F&G）」—— **该用途已废弃**（CNN F&G 不再采集），已从表中删除。

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

> ⚠️ 此前还有一条「网络可访问 CNN F&G 接口（国内可能需要代理）」——**该外部依赖已移除**。

---

## CLI 命令

共 **18 个命令**，完整清单与「是否需 OpenD」见根目录 [`README.md`](../../../README.md) 的「全部 CLI 命令」表。常用：

```bash
# 启动 API 服务
trader-analysis serve --host 0.0.0.0 --port 8000

# 启动 API 服务（开发模式，代码修改后自动重载）
uvicorn trader_analysis.futu_strategy.api_server:app --host 0.0.0.0 --port 8000 --reload --reload-dir src

# 历史数据初始化（断点续传，自动跳过已有数据）
trader-analysis init
trader-analysis init --codes US.AAPL --codes US.TSLA
trader-analysis init --force
trader-analysis init --start 2022-06-01

# 每日增量更新
trader-analysis update

# 纯本地评分 / 市场温度（不需要 OpenD）
trader-analysis score
trader-analysis temperature

# 信号扫描
trader-analysis scan-signals
trader-analysis livermore --top 10

# 完整策略流程（增量更新 → 评分 → 交易）
trader-analysis run
```

> **注意**：`data/indicators.db` 为纯本地文件（已加入 .gitignore），clone 后需重新运行 `trader-analysis init` 拉取数据。

---

## 异常处理策略

| 所属层 | 异常场景 | 处理方式 |
|--------|---------|---------|
| A 数据获取 | OpenD 连接失败 | 启动时检测，失败直接退出并提示 |
| A 数据获取 | 历史 K 线额度不足 | 打印警告，跳过本标的，继续下一个 |
| A 指标计算 | 数据不足（K 线 < 250 根） | 跳过 MA250 指标，该项得 0 分 |
| A 交易执行 | 模拟账户购买力不足 | 捕获错误，写日志，不中断 |
| A 交易执行 | 重复买入 | 下单前查持仓，**已持有即跳过**（`ALLOW_PYRAMID=False`，与信号等级无关） |
| B 存储层 | 数据库文件不存在 | `init_db()` 自动建表 |
| B 存储层 | UPSERT 冲突 | `INSERT OR REPLACE` 自动覆盖旧数据 |
| B 初始化 | 中途失败 | 断点续传，重新运行自动跳过已完成标的 |
| C API 层 | 查询的标的无数据 | **返回 HTTP 200 + `{data: null, message}`** |

> ⚠️ **勘误（2026-10-12）**：
> ① 删除了两条已失效的场景 ——「CNN F&G 接口超时/失败，该项得 0 分」与「VIX 数据获取失败，该项得 0 分」，
> 因为这两项数据已不在评分路径上（不再采集）；
> ② 删除了「MACD 背离检测谷底不足 2 个」—— `scorer.py` 不调用背离检测；
> ③ **重复买入规则**此前写「已持有且**非 STRONG_BUY** 则跳过」，实际是
> `trade_executor.py:63-67`：`if not config.ALLOW_PYRAMID:` 时**只要已持有就跳过**（`ALLOW_PYRAMID` 默认 `False`），
> **与信号等级无关**；
> ④ API 层「返回 404」改为 **HTTP 200 + `data: null`**（v2.3 起统一）。

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

### VIX 和 CNN F&G —— ⚠️ 已废弃（2026-10-12 勘误）

> 本节此前写「两者是市场级数据（与个股无关），同一次运行只获取一次，模块级缓存复用」。
> **现状：这两项数据已不再采集，也不参与任何评分。**
> - `external_data.py` **模块已从仓库删除**
> - `scorer.py` 的 6 个因子里没有它们
> - `market_scorer.py` 的 3 个维度（日线技术 50% / 周线技术 35% / 价格位置 15%）也不含 VIX
> - `config.MARKET_TEMP_VOL_CODE` 虽有定义，但注释已标明「保留定义供历史兼容，实际不再使用」；
>   `market_scorer.py` 中 `vix_value` 固定为 `None`
>
> 前端 `MarketTemperature.vue` 底部仍有一行 **VIX 观察提示文案**，但那只是给人看的提醒，**不参与计算**。

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

*文档版本：v2.3 | 最后更新：2026-05-05*
*适用环境：富途 OpenAPI + Python 3.10+ | 交易环境：模拟盘（SIMULATE）*
