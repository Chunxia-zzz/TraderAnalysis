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
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/watchlist` | 标的池（含分类、标签、数据状态） |
| GET | `/api/indicators?code=US.AAPL&ktype=1d&days=60` | K 线 + 技术指标 |
| GET | `/api/indicators/latest?code=US.AAPL` | 最新一根指标值 |
| GET | `/api/scores/latest?code=US.AAPL` | 最新评分结果 |

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

## Docker

```bash
docker build -t trader-analysis .
docker run -p 8000:8000 -v $(pwd)/data:/app/data trader-analysis
```

注意：容器内只运行 API 服务，历史数据初始化需在宿主机完成（需连接 OpenD）。
