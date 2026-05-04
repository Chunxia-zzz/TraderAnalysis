# TraderAnalysis

Futu 量化评分与模拟盘交易系统。基于 40 只核心观察标的，通过多指标加权评分（0~100 分）自动触发模拟盘买入。

## 架构

三层架构，通过 SQLite 解耦：

- **Part A — 后端核心层**：K 线拉取、指标计算、9 项加权评分、模拟盘交易
- **Part B — 持久化存储层**：SQLite 存储 K 线 + 指标 + 评分，支持历史初始化和每日增量更新
- **Part C — API 服务层**：FastAPI 只读接口，供前端消费，不依赖 Futu OpenD

详细技术方案见 [`docs/futu_strategy_docs/futu_strategy_docs/README.md`](docs/futu_strategy_docs/futu_strategy_docs/README.md)

## 前置条件

- Python 3.10+
- [富途 OpenD](https://openapi.futunn.com/) 运行在 `127.0.0.1:11111`
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
trader-analysis init
```

- 自动从 `data/watchlist.json` 读取 40 只标的
- 每只拉取 1000 根日线 + 200 根周线，计算全部技术指标后写入 `data/indicators.db`
- 支持断点续传：中断后重新运行，已完成的标的会自动跳过
- 可选参数：`--codes US.AAPL US.TSLA`（指定标的）、`--force`（强制重拉）

### 3. 启动 API 服务

```bash
trader-analysis serve --host 0.0.0.0 --port 8000
```

Swagger 文档：`http://localhost:8000/docs`

### 4. 日常运维

```bash
# 每日增量更新（建议收盘后定时运行）
trader-analysis update

# 完整策略流程：增量更新 → 评分 → 模拟盘交易
trader-analysis run

# 市场温度评分（6 维度综合评分 + 目标仓位建议）
trader-analysis temperature
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/watchlist` | 标的池（含分类、标签、数据状态） |
| GET | `/api/indicators?code=US.AAPL&ktype=1d&days=60` | K 线 + 技术指标 |
| GET | `/api/indicators/latest?code=US.AAPL` | 最新一根指标值 |
| GET | `/api/scores/latest?code=US.AAPL` | 最新评分结果 |
| GET | `/api/market-temperature` | 市场温度评分（6 维度综合） |
| GET | `/api/market-temperature/history?days=30` | 市场温度历史趋势 |

详细接口文档见 [`docs/api.md`](docs/api.md)

## 标的池

通过 `data/watchlist.json` 管理，当前包含 40 只标的，覆盖 10 个板块：

大盘/黄金/BTC、存储、光通信、MAG7、加密、半导体、太空、云、中概、防守消费

新增或删除标的只需编辑 JSON 文件，下次运行 `init` 或 `update` 时自动生效。

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest tests/ -v

# 代码检查
ruff check src/ tests/
```

## Docker 部署

### 本地 / 单机部署（推荐）

```bash
# 构建镜像
docker compose build

# 首次部署：初始化历史数据（需要 OpenD 在宿主机运行）
docker compose run --rm trader-init

# 启动服务（API + 定时任务）
docker compose up -d

# 查看日志
docker compose logs -f trader-api

# 手动触发市场温度计算
docker compose exec trader-api python -m trader_analysis temperature
```

### docker-compose.yml 说明

| 服务 | 作用 | 启动方式 |
|------|------|---------|
| `trader-api` | API 服务 + cron 定时任务 | `docker compose up -d` |
| `trader-init` | 一次性历史数据初始化 | `docker compose run --rm trader-init` |

### 定时任务（已内置）

容器内 cron 自动执行：

| 时间（北京） | 任务 |
|-------------|------|
| 每日 04:15（周一至周六） | `update` 增量更新 + `temperature` 市场温度计算 |

### 数据持久化

```
./data/indicators.db  ← SQLite 数据库（挂载为 Docker Volume）
./logs/               ← 运行日志
```

> `data/*.db` 和 `logs/` 已加入 .gitignore，纯本地/容器内数据。

---

## 云服务器部署指南

目标环境：阿里云轻量应用服务器（2 核 2G），Docker Compose + SQLite。

### 已就绪（现在直接可用）

- [x] Dockerfile 多阶段构建（镜像约 200MB）
- [x] docker-compose.yml（API + 定时任务一体）
- [x] 定时任务容器化（cron，北京时间 04:15 自动更新）
- [x] 环境变量配置（.env.example）
- [x] 健康检查（/health 端点 + Docker HEALTHCHECK）
- [x] 数据持久卷挂载（SQLite 不丢数据）
- [x] 非 root 用户运行（安全）

### 部署时需要做的

| 步骤 | 操作 | 说明 |
|------|------|------|
| 1 | 安装 Docker + Docker Compose | `curl -fsSL https://get.docker.com \| sh` |
| 2 | 安装 OpenD | 从富途官网下载 Linux 版，登录账号 |
| 3 | 克隆代码 | `git clone` 到服务器 |
| 4 | 配置 .env | `cp .env.example .env`，设置 `FUTU_OPEND_HOST=127.0.0.1` |
| 5 | 初始化数据 | `docker compose run --rm trader-init` |
| 6 | 启动服务 | `docker compose up -d` |
| 7 | 配置 Nginx 反代 | 可选：域名 + HTTPS + 转发到 8000 端口 |
| 8 | 安全组 | 开放 8000（或 80/443 如果用 Nginx） |

### OpenD 注意事项

- OpenD 需要在**宿主机**运行（不在 Docker 内），容器通过 `host.docker.internal`（Mac/Win）或 `172.17.0.1`（Linux）连接
- Linux 服务器上 `.env` 中设置 `FUTU_OPEND_HOST=172.17.0.1`
- OpenD 需保持登录状态，建议用 `nohup` 或 systemd 托管
- 模拟账户即可，无需实盘权限

### 内存优化（2G 服务器）

- SQLite 比 PostgreSQL 省内存，当前方案足够
- Python 进程约占 150MB，OpenD 约占 300MB，剩余 ~1.5G 余量充足
- 如果内存紧张，可关闭 OpenD 的行情推送功能
