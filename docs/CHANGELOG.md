# Changelog

本文件记录项目的重大版本变更。格式参考 [Keep a Changelog](https://keepachangelog.com/)。

---

## [v2.1.0] — 2026-04-23

### 重构
- 删除已废弃模块：`indicators/`、`signals/`、`notify/`、`backtest/`、`strategy/`、`api/`、`examples/`
- 合并 `data/providers.py` + `data/schemas.py` → `futu_strategy/providers.py`（只保留 FutuLiveDataProvider）
- 删除无用数据源：CSVDataProvider、FutuJsonDataProvider、ParquetDataProvider
- CLI 从 3 命令（backtest/signals/serve）改为 4 命令（serve/init/update/run）
- 项目结构精简为：`cli.py` + `futu_strategy/`（完整三层架构）

### 新增
- `config.py`：WATCHLIST 从 `data/watchlist.json` 动态加载（40 只标的，10 个分类）
- `api_server.py`：`/api/watchlist` 返回完整标的信息（name/category/tags/has_data）
- `api_server.py`：指标/评分接口无数据时返回 HTTP 404 + 描述性提示
- `init_history.py`：断点续传（自动跳过已有数据）+ 频率控制（3 秒间隔）+ `--force` 参数
- 新测试套件：test_smoke / test_config / test_storage / test_api（25 个测试）

### 变更
- `__init__.py` 版本号修正为 `0.2.0`（与 pyproject.toml 一致）
- `pyproject.toml` 描述更新为 Futu 量化评分系统
- `Dockerfile` 更新环境变量和 healthcheck
- `.env.example` 更新为当前可用的环境变量

### 文档
- 主技术方案 README.md 重写：删除 v1→v2 迁移指引和已删模块说明，更新项目结构和 CLI 命令
- API 文档 api.md 重写：删除废弃的 api/app.py 服务，更新响应格式
- part_c_api.md 更新 watchlist 响应格式和 404 处理
- part_b_storage.md 更新 init_history 断点续传说明

---

## [v2.0.0] — 2026-04-20

### 架构变更
- futu_strategy 模块从单层架构升级为**三层架构**：后端核心层(Part A) → 持久化存储层(Part B) → API 服务层(Part C)
- 指标计算与评分逻辑解耦：`indicators.py` 只追加数值列，`scorer.py` 只做阈值判断

### 新增
- `futu_strategy/storage.py` — SQLite 持久化层（`kline_indicators` + `score_results` 两张表）
- `futu_strategy/indicators.py` — 配置驱动的通用指标计算函数 `calc_indicators(df, config)`
- `futu_strategy/init_history.py` — 一次性历史数据初始化脚本
- `futu_strategy/daily_update.py` — 每日增量更新脚本（拼接历史后重算指标）
- `futu_strategy/api_server.py` — FastAPI 只读 API（4 个端点，独立于 Futu OpenD）
- `config.py` 新增 `DAILY_INDICATOR_CONFIG`、`WEEKLY_INDICATOR_CONFIG`、`DB_PATH`、`INIT_*_KLINE_COUNT`
- `pyproject.toml` 新增 `scipy` 依赖

### 变更
- `scorer.py` — 不再自行调用 `calc_*` 计算指标，改为从预计算好的 DataFrame 直接读值评分
- `runner.py` — 主流程改为：增量更新存储层 → 从 storage 读指标 → 评分 → 写回存储 → 交易
- 项目版本号从 `0.1.0` 升至 `0.2.0`

### 文档
- 合并旧 `docs/architecture.md` 内容到 `docs/futu_strategy_docs/futu_strategy_docs/README.md`，作为项目整体技术方案
- 删除 `docs/architecture.md`（内容已合并）

---

## [v1.0.0] — 2026-04-14

### 新增
- futu_strategy 模拟盘策略包：9 项指标加权评分（0~100），70 分触发买入，90 分强烈买入
- 数据获取：K 线（日线 250 根 + 周线 60 根）、VIX 快照、CNN Fear & Greed
- 评分引擎：周线 RSI、日线 MACD 背离、VIX、布林带、日线 RSI、CNN F&G、恐慌放量缩量、MA200 偏离、周线 MACD 缩小
- 模拟盘交易执行：限价单下单、持仓检查、防重复买入
- JSONL 日志：评分记录 + 交易记录
- HTTP API 服务：FastAPI 实时指标查询（/v1/indicators/\*、/v1/signals/\*）
- 共享层：OHLCV Schema、多数据源（CSV/JSON/Parquet/Live Futu）、IndicatorSpec 流水线
- 信号模块、策略框架、回测引擎
- CLI 入口（typer）
- Docker 支持
