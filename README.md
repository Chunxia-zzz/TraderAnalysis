# TraderAnalysis

Futu 量化评分与模拟盘交易系统。基于 203 只核心观察标的，通过 6 因子连续映射评分、道氏理论三层趋势分析、晨星公允价值估值，自动识别高置信度做多机会。

🌐 [体验地址](http://47.106.175.84/)

## 架构

三层架构，通过 SQLite 解耦：

- **Part A — 后端核心层**：K 线拉取、指标计算、6 因子连续评分、市场温度、模拟盘交易
- **Part B — 持久化存储层**：SQLite 存储 K 线 + 指标 + 评分，支持历史初始化和每日增量更新
- **Part C — API 服务层**：FastAPI 只读接口，供前端消费，不依赖 Futu OpenD

详细技术方案见 [`docs/futu_strategy_docs/futu_strategy_docs/README.md`](docs/futu_strategy_docs/futu_strategy_docs/README.md)

## 前置条件

- Python 3.10+
- [富途 OpenD](https://openapi.futunn.com/) 运行在 `127.0.0.1:11111`（仅初始化和增量更新时需要）
- 已登录富途账号，模拟账户可用

## 部署上线

### 1. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
pip install futu-api
```

### 2. 初始化历史数据

确保 OpenD 已启动，然后拉取全部标的的历史 K 线并计算指标：

```bash
# 默认拉取（约 250 根日线）
trader-analysis init

# 拉取更长历史（约 4 年，推荐）
trader-analysis init --start 2022-06-01 --force
```

- 自动从 `data/watchlist.json` 读取 40 只标的
- 支持断点续传：中断后重新运行，已完成的标的会自动跳过
- 可选参数：`--codes US.AAPL US.TSLA`（指定标的）、`--force`（强制重拉）

### 3. 启动 API 服务

```bash
# 前台启动
trader-analysis serve --host 0.0.0.0 --port 8000

# 后台持久化启动（推荐，终端关闭后不中断）
nohup python -m trader_analysis serve --host 0.0.0.0 --port 8000 > logs/server.log 2>&1 &
```

Swagger 文档：`http://localhost:8000/docs`
健康检查：`http://localhost:8000/health`

### 4. 日常运维

```bash
# 每日增量更新（需要 OpenD，建议收盘后定时运行）
trader-analysis update

# 纯本地评分（不需要 OpenD，从 DB 读指标计算）
trader-analysis score
trader-analysis score --backfill 900   # 回溯 900 天历史评分

# 市场温度评分（3 维度综合评分 + 目标仓位建议）
trader-analysis temperature
trader-analysis temperature --backfill 900

# 信号回测（3 种模式：买入持有 / 波段操作 / 趋势跟踪）
trader-analysis backtest US.SNDK --mode hold --threshold 40 --holding-days 10
trader-analysis backtest US.NVDA --mode swing --threshold 60 --exit-threshold 30
trader-analysis backtest US.MU --mode trend --threshold 40 --trail-ma ma10
trader-analysis backtest US.MU --mode trend --threshold 40 --trail-ma ma10 --entry-confirm above_ma5

# 网格交易引擎（日内自动交易，需要 OpenD）
trader-analysis grid-create --code US.GLD --upper 445 --lower 425 --grid-count 10 --order-qty 10
trader-analysis grid-start 1       # 启动（长驻进程）
trader-analysis grid-status 1      # 查看状态
trader-analysis grid-stop 1        # 停止

# 完整策略流程：增量更新 → 评分 → 模拟盘交易（需要 OpenD）
trader-analysis run
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/watchlist` | 标的池（含晨星折价、最新收盘价、分类标签） |
| GET | `/api/indicators?code=US.AAPL&ktype=1d&days=60` | K 线 + 技术指标（支持 1d/4h/1w） |
| GET | `/api/indicators/latest?code=US.AAPL` | 最新一根指标值 |
| GET | `/api/scores/latest?code=US.AAPL` | 个股 6 因子评分（支持日期筛选） |
| GET | `/api/scores/overview` | 全标的评分速览（含动量分+MA5确认） |
| GET | `/api/analysis?code=US.AAPL` | 道氏三层趋势 + 支撑压力 + 形态置信度 + 盈亏比 |
| GET | `/api/fundamental?code=US.AAPL` | 基本面估值（分析师目标价 + 晨星公允价值） |
| GET | `/api/daily-picks` | 高置信度低估做多机会（巴菲特原则筛选） |
| GET | `/api/ema-cross-signals` | EMA5/30 交叉信号（空转多/多转空） |
| GET | `/api/market-temperature` | 市场温度评分（3 维度综合） |
| GET | `/api/market-temperature/history?days=30` | 市场温度历史趋势 |
| GET | `/api/backtest/run?code=US.SNDK&mode=trend` | 信号回测（3种策略模式） |

所有接口无数据时返回 HTTP 200 + `{data: null, message: "提示文案"}`。

详细接口文档见 [`docs/api.md`](docs/api.md)

## 标的池

通过 SQLite `watchlist` 表 + RESTful API 管理，当前包含 196 只标的（美股 193 + 港股 3），覆盖 26 个板块：

大盘/黄金/BTC、存储、光通信、MAG7、加密、半导体、太空、云、中概、防守消费、AI 基建、金融、医疗、能源、工业等。

**加入规则**（详见 [`docs/futu_strategy_docs/futu_strategy_docs/part_e_watchlist_management.md`](docs/futu_strategy_docs/futu_strategy_docs/part_e_watchlist_management.md)）：
- 纳入：大市值龙头（≥ $50B）、覆盖主要行业、可估值（有晨星/分析师目标价）
- 排除：杠杆/反向 ETF、重复的行业 ETF、无法估值的股票

**管理方式**：通过 API 增删改查（标的管理页或 `POST/PATCH/DELETE /api/watchlist`），新增后跑 `init` 拉历史数据，`score`/`scan-signals` 纳入评分与信号。`config.WATCHLIST` 动态从 DB 读取，无需重启。

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest tests/ -v

# 代码检查
ruff check src/ tests/
```

---

## 日常更新线上服务

> 服务器访问 GitHub 不稳定，采用 **Git bare repo** 方案：服务器同时作为 git remote，
> 本地一次 `git push` 同时推送 GitHub（备份）和服务器（自动部署）。
> 以下命令均在**本地 Windows Git Bash** 中执行。
> 服务器信息：`root@47.106.175.84`

### 原理

```
git push origin main
       │
       ├──→  GitHub（备份/历史）
       │
       └──→  服务器裸仓库（/opt/git/trader-analysis.git）
                  │
                  └──→  post-receive hook 自动执行
                              ├── git checkout → /opt/trader-analysis/
                              └── systemctl restart trader-api
```

服务器不需要访问 GitHub，本地推送到服务器，hook 触发部署，全程自动。

### 1. 更新后端 / 前端代码

```bash
# 后端
cd /f/TraderAnalysis
git add . && git commit -m "your message"
git push origin main   # 同时推 GitHub + 服务器，服务器自动重启 trader-api

# 前端
cd /f/TraderAnalysisFrontend
git add . && git commit -m "your message"
git push origin main   # 同时推 GitHub + 服务器，服务器自动 npm build 并更新静态文件
```

### 2. 同步行情数据库

本地跑完 update / temperature / score 后，同步 db 到服务器：

```bash
scp /f/TraderAnalysis/data/indicators.db \
    root@47.106.175.84:/opt/trader-analysis/data/indicators.db
```

### 4. 常用服务器命令

登录服务器后可用：

```bash
systemctl status trader-api        # 查看后端状态
systemctl restart trader-api       # 重启后端
journalctl -u trader-api -n 50     # 查看后端日志
```
