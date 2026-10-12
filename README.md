# TraderAnalysis

Futu 量化评分与模拟盘交易系统。基于 195 只核心观察标的，通过 6 因子连续映射评分、道氏理论三层趋势分析、晨星公允价值估值，自动识别高置信度做多机会。

> **两套并行的信号体系**（刻意不合并）：
> ① **6 因子评分**（`total_score`）—— 纯均值回归，6 个因子全部「越低/越跌 → 分越高」，买超卖；
> ② **利弗莫尔关键点**（`livermore_signal_log`）—— 买**突破**，只看整理平台上沿 + 量能确认 + 周线潮汐顺势。
> 两者方向相反，因此利弗莫尔信号**不并入 `total_score`**、不写 `top/bottom_signal_log`，独立落库、独立 API、独立页面（`/livermore`）。
> 也正因如此，系统里的「支撑压力位」是 Swing Pivot 聚类，**与利弗莫尔关键点不是一回事**，勿混称。

🌐 [体验地址](http://47.106.175.84/)

## 架构

三层架构，通过 SQLite 解耦：

- **Part A — 后端核心层**：K 线拉取、指标计算、6 因子连续评分、市场温度、模拟盘交易
- **Part B — 持久化存储层**：SQLite 存储 K 线 + 指标 + 评分 + 信号 + 标的池，支持历史初始化和每日增量更新
- **Part C — API 服务层**：FastAPI 接口，供前端消费

> ⚠️ **Part C 不是「只读」也不完全独立于 OpenD**：`api_server.py` 有 **8 个写端点**
> （`POST/PUT/DELETE`，如标的池增删改、目标仓位保存、文案模板），且以下端点在请求时会直连 Futu OpenD：
> `POST /api/watchlist`（调 `fetch_stock_info` 补全快照）、`POST /api/watchlist/refresh-snapshot`（调 `fetch_snapshot_batch`）、
> `GET /api/position`、`GET /api/allocation`。**只读的只是评分/指标/信号那一大类。**

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

- 标的池由 **SQLite `watchlist` 表**提供（当前 **195 只**）；`data/watchlist.json`（49 条）只作**表为空时的回退**
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

# 扫描交易信号（顶/底/EMA 交叉 + 利弗莫尔关键点，需要 OpenD 拉最新行情）
trader-analysis scan-signals
trader-analysis scan-signals --backfill 30   # 回溯 30 个交易日

# 利弗莫尔关键点（独立信号体系，不并入评分）
trader-analysis livermore --top 10              # 四分组打印：突破 / 逼近 / 已在关键点上方 / 风险
trader-analysis livermore --all                 # 不做周线潮汐过滤，看全部突破
trader-analysis livermore --backfill 20         # 逐日回填语义（隐含 --persist，写 livermore_signal_log）
trader-analysis livermore --date 2026-10-09 --persist   # 按指定日期回算并落库

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

**全部 CLI 命令（共 18 个，2026-10-12 核对）**

| 命令 | 说明 | 需要 OpenD |
|------|------|:---:|
| `serve` | 启动 FastAPI 服务 | ✗ |
| `init` | 拉取历史 K 线并计算指标（支持 `--codes` / `--force` / `--start`） | ✓ |
| `update` | 增量更新 K 线与指标（每日收盘后） | ✓ |
| `run` | 完整策略流程：增量更新 → 评分 → 模拟盘交易 | ✓ |
| `score` | 纯本地评分：从 DB 读指标计算并写 `score_results`（支持 `--backfill N`） | ✗ |
| `temperature` | 市场温度评分 + 目标仓位建议（支持 `--backfill N`） | ✗ |
| `scan-signals` | 扫描顶/底信号并落库（支持 `--backfill N`） | ✗ |
| `scan-top` | 只扫顶背离预警（不依赖 OpenD） | ✗ |
| `livermore` | 利弗莫尔关键点扫描（`--top` / `--all` / `--date` / `--persist` / `--backfill N`） | ✗ |
| `backtest` | 信号回测（5 种模式：`hold` / `swing` / `trend` / `ribbon_long` / `ribbon_short`） | ✗ |
| `fundamental` | 拉取基本面数据并评分（数据源 yfinance） | ✗ |
| `migrate-watchlist` | `watchlist.json` → SQLite 一次性迁移 | ✗ |
| `refresh-snapshot` | 刷新标的池静态快照字段（`trailing_pe` / `market_cap` 等） | ✓ |
| `grid-create` / `grid-start` / `grid-stop` / `grid-status` | 网格交易引擎四件套 | ✓ |
| `create-admin` | ⚠️ **当前不可用**：内部 `from ...auth import hash_password` / `...auth_storage import create_user`，而 `auth.py`、`auth_storage.py` **已随认证体系一并从仓库移除** → 执行会 `ImportError` | — |

## API 接口

共 **38 个路由**（只读 30 + 写 8，2026-10-12 核对；完整参数与响应见 [`docs/api.md`](docs/api.md)）。

**只读（30）**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/watchlist` | 标的池（含晨星折价、最新收盘价、分类标签） |
| GET | `/api/watchlist/{code}` | 单个标的信息 |
| GET | `/api/indicators?code=US.AAPL&ktype=1d&days=60` | K 线 + 技术指标（支持 1d/4h/1w） |
| GET | `/api/indicators/latest?code=US.AAPL` | 最新一根指标值 |
| GET | `/api/scores/latest?code=US.AAPL` | 个股 6 因子评分（支持日期筛选） |
| GET | `/api/scores/overview` | 全标的评分速览（含动量分+MA5确认） |
| GET | `/api/analysis?code=US.AAPL&ktype=1d` | 道氏三层趋势 + 支撑/压力关键位（Swing Pivot 聚类）+ 形态置信度 + 盈亏比 |
| GET | `/api/fundamental?code=US.AAPL` | 基本面估值（分析师目标价 + 晨星公允价值） |
| GET | `/api/daily-picks` | 高置信度低估做多机会（巴菲特原则筛选） |
| GET | `/api/ema-cross-signals` | EMA5/30 交叉信号（空转多/多转空） |
| GET | `/api/top-signals` | 顶部信号（顶背离 / 顶部预警） |
| GET | `/api/bottom-signals` | 底部信号 |
| GET | `/api/trade-signals` | 顶/底交易信号 |
| GET | `/api/tp-sl` | 止盈止损位计算 |
| GET | `/api/livermore/signals` | 利弗莫尔关键点信号（独立体系；四分组：突破/逼近/已在关键点上方/风险），支持 `date`/`source`/`all`/`refresh` |
| GET | `/api/livermore/detail?code=US.AAPL` | 单标的利弗莫尔关键点全景（箱体/关键点/止损/金字塔/潮汐/相对强度）+ 可画线 `levels` |
| GET | `/api/market-temperature` | 市场温度评分（3 维度综合） |
| GET | `/api/market-temperature/history?days=30` | 市场温度历史趋势 |
| GET | `/api/asset-temperature/history?asset=GLD&days=60` | 黄金/比特币资产温度历史 |
| GET | `/api/position?env=real` | 实时持仓（**需 OpenD**） |
| GET | `/api/position-states?code=US.AAPL` | 持仓状态（不传 code 返回所有非 EMPTY 持仓） |
| GET | `/api/allocation?env=real` | 目标仓位配置 + 偏离 + 加仓建议（**需 OpenD**） |
| GET | `/api/sell-log?days=30` | 卖出日志（读 `trade_log.jsonl` 的 SELL 记录） |
| GET | `/api/backtest/run?code=US.SNDK&mode=trend` | 信号回测（5 种策略模式） |
| GET | `/api/review?type=daily` | 日/周复盘报告 |
| GET | `/api/content-generator?code=US.AAPL` | 自媒体文案生成 |
| GET | `/api/content-templates` | 文案模板列表 |
| GET | `/api/grid/status` | 网格引擎运行状态 |
| GET | `/api/grid/orders` | 网格成交订单 |

**写（8）**

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/watchlist` | 新增标的（**需 OpenD** 补全快照） |
| POST | `/api/watchlist/batch` | 批量新增 |
| POST | `/api/watchlist/refresh-snapshot` | 批量刷新快照（**需 OpenD**） |
| PATCH | `/api/watchlist/{code}` | 编辑标的（仅白名单字段） |
| DELETE | `/api/watchlist/{code}` | 删除标的 |
| PUT | `/api/allocation` | 保存目标仓位配置 |
| PUT | `/api/content-templates/{key}` | 保存文案模板 |
| DELETE | `/api/content-templates/{key}` | 删除文案模板 |

所有接口无数据时返回 **HTTP 200 + `{data: null, message: "提示文案"}`**（不是 404）。

详细接口文档见 [`docs/api.md`](docs/api.md)

## 标的池

通过 SQLite `watchlist` 表 + RESTful API 管理，当前包含 195 只标的（美股 192 + 港股 3：HK.00700 / HK.01211 / HK.03690），覆盖 26 个分类：

大盘/黄金/BTC、存储、光通信、MAG7、加密、半导体、太空、云、中概、防守消费、AI 基建、金融、医疗、能源、工业等。

**加入规则**（详见 [`docs/futu_strategy_docs/futu_strategy_docs/part_e_watchlist_management.md`](docs/futu_strategy_docs/futu_strategy_docs/part_e_watchlist_management.md)）：
- 纳入：大市值龙头（≥ $50B）、覆盖主要行业、可估值（有晨星/分析师目标价）
- 排除：杠杆/反向 ETF、重复的行业 ETF、无法估值的股票

**管理方式**：通过 API 增删改查（标的管理页或 `POST/PATCH/DELETE /api/watchlist`），新增后跑 `init` 拉历史数据，`score`/`scan-signals` 纳入评分与信号。`config.WATCHLIST` 是**动态属性**，每次访问从 DB 读取，无需重启。

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

### 3. 常用服务器命令

登录服务器后可用：

```bash
systemctl status trader-api        # 查看后端状态
systemctl restart trader-api       # 重启后端
journalctl -u trader-api -n 50     # 查看后端日志
```

### 4. Nginx 层：静态压缩与缓存（2026-10-12 新增）

> 此前 nginx 配置**只存在于服务器上、仓库里没有记录**。本节把它固化，避免以后不知道
> `/etc/nginx/conf.d/gzip.conf` 是干什么的。原配置备份在服务器 `/root/nginx-backup/`。

**背景**：`/etc/nginx/nginx.conf:29` 的 `#gzip  on;` **一直是注释状态** → 线上 JS 原样传输。
实测 index 主包 1531 KB 未压缩，开启后 480 KB；整页首屏实际下载 **1688 KB → 575 KB（省 66%）**。

**两处配置**

| 文件 | 作用 |
|---|---|
| `/etc/nginx/conf.d/gzip.conf` | gzip 压缩开关与类型（含 `gzip_proxied any` → `/api` 反代响应也压缩） |
| `/etc/nginx/conf.d/trader.conf` | 站点块，新增 `/assets/` 强缓存与 `index.html` no-cache |

`conf.d/*.conf` 由 `nginx.conf:31` 在 `http` 块内 include，所以 `gzip.conf` 里写 http 级指令是合法的 ——
**新增独立文件而不是改 `nginx.conf`**，删除该文件即可回滚。

**三个必须知道的坑**

1. **不要叠加 `expires` 指令**。`expires 1y` 本身就会输出 `Cache-Control: max-age=...`，
   再 `add_header Cache-Control "..., immutable"` 会让 nginx 输出**两个 Cache-Control 头**。
   本项目只用 `add_header`。验证：`curl -sD- -o/dev/null <url> | grep -ci cache-control` 必须是 1。
2. **`index.html` 必须 `no-cache`**。Vite 产物名带内容 hash，`/assets/` 一旦被永久强缓存，
   而 `index.html` 也被启发式缓存住，新部署后页面仍会去请求**已删除的旧 chunk → 白屏**。
   `no-cache` 是每次带 ETag 重验证（命中返 304），成本极低。
3. **`application/javascript` 必须显式列进 `gzip_types`**。nginx 默认只压 `text/html`，
   而 `.js` 的 MIME 是 `application/javascript`，不写进去等于没压。

**改动后如何验证**

```bash
# 语法校验（不通过就不要 reload）
ssh root@47.106.175.84 "nginx -t"
# 平滑重载（不断连接）
ssh root@47.106.175.84 "systemctl reload nginx"

# 压缩是否生效：应看到 Content-Encoding: gzip，且 size 从 1567955 降到约 491000
curl -s -o /dev/null -H 'Accept-Encoding: gzip' \
  -w "传输 %{size_download} bytes\n" \
  http://47.106.175.84/assets/index-<hash>.js

# 缓存头是否生效
curl -sD- -o /dev/null http://47.106.175.84/assets/index-<hash>.js | grep -i cache-control  # immutable
curl -sD- -o /dev/null http://47.106.175.84/                          | grep -i cache-control  # no-cache
```

> 改 nginx 后**务必回归一遍站点**：7 个 SPA 路由返回 200、`/api` 反代正常、页面无 JS 异常。
