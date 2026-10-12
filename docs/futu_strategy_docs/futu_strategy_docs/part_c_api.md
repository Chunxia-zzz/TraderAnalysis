# Part C — API 服务层（api_server.py）

> API 层将存储层的数据暴露为 HTTP 接口，供前端消费。**绝大多数端点只做读取**，不调用 Futu SDK、不做计算，可独立于后端进程运行。
>
> **⚠️ 例外**：`/api/position`（持仓查询）与 `/api/allocation`（目标仓位，含 `PUT` 保存）依赖**本机 Futu OpenD（127.0.0.1:11111）** 实时查询，不能脱离后端环境。
>
> 源码位置：`src/trader_analysis/futu_strategy/api_server.py`
> **完整端点清单、请求参数、响应样例请以 [`docs/api.md`](../../../api.md) 为准**（本文档只讲架构与通用约定，不再逐条复制）。

---

## 功能清单（按分组）

| 分组 | 端点数 | 说明 |
|------|--------|------|
| 健康检查 | 1 | `GET /health` |
| 指标 | 2 | `GET /api/indicators`、`/api/indicators/latest` |
| 个股评分 | 2 | `GET /api/scores/latest`、`/api/scores/overview` |
| 标的池 CRUD | 7 | `GET/POST /api/watchlist`、`GET/PATCH/DELETE /api/watchlist/{code}`、`POST /api/watchlist/batch`、`POST /api/watchlist/refresh-snapshot` |
| 市场温度 | 3 | `GET /api/market-temperature`、`/api/market-temperature/history`、`/api/asset-temperature/history` |
| 信号 | 6 | `GET /api/top-signals`、`/api/bottom-signals`、`/api/ema-cross-signals`、`/api/trade-signals`、`/api/livermore/signals`、`/api/livermore/detail` |
| 复盘与文案 | 7 | `GET /api/analysis`、`/api/daily-picks`、`/api/content-generator`、`/api/review`、`/api/content-templates`、`PUT/DELETE /api/content-templates/{key}` |
| 交易执行 | 5 | `GET /api/position-states`、`/api/sell-log`、`/api/tp-sl`、`/api/grid/status`、`/api/grid/orders` |
| 回测 | 1 | `GET /api/backtest/run` |
| 持仓与配置 | 3 | `GET /api/position`、`GET/PUT /api/allocation` |
| 基本面 | 1 | `GET /api/fundamental` |

> 合计 **37 个业务端点 + 1 个健康检查 = 38 条路由**。
> 其中 **8 个为写端点**（`POST/PUT/DELETE`）：标的池 5 个（增/改/删/批量增/刷新快照）、
> 文案模板 2 个（`PUT`/`DELETE`）、目标仓位 1 个（`PUT`）——**API 层并非纯只读**。
> （本文件初版只设计了 4 个端点，见文末「历史沿革」。）

---

## 实现思路

- 使用 **FastAPI** 框架：轻量、自带 Swagger 文档（`/docs`）
- 所有接口只读 SQLite，调用 `storage.py` / `watchlist_storage.py` 的查询函数
- **不连接 Futu OpenD**（`/api/position`、`/api/allocation` 除外）
- CORS 全开放：`allow_origins=["*"]`、`allow_methods=["*"]`、`allow_headers=["*"]`（**不是仅 GET**）
- 服务**无鉴权，全开放**
- 启动时执行 `@app.on_event("startup")` 钩子：`storage.init_db()` + `watchlist_storage.init_watchlist_table()` + `template_store.init_templates_table()`（幂等建表，无需手工初始化）

---

## 具体实现方案

### 应用骨架

```python
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Strategy Indicators API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def _ensure_db() -> None:
    storage.init_db()
    watchlist_storage.init_watchlist_table()
    from trader_analysis.futu_strategy.template_store import init_templates_table
    init_templates_table()
```

### 启动命令

```bash
uvicorn trader_analysis.futu_strategy.api_server:app --host 0.0.0.0 --port 8000

# Swagger 文档地址：http://localhost:8000/docs
```

---

## 通用约定（重要）

### 1. 无数据时统一返回 HTTP 200 + `data: null`

**不再返回 404。** 前端通过 `data` 字段判空，`message` 用于提示：

```json
{
  "data": null,
  "message": "US.FAKECODE 暂无评分数据"
}
```

`/api/indicators` 是唯一格式略有差异的端点（保留 `code` / `ktype` 上下文）：

```json
{
  "code": "US.FAKECODE",
  "ktype": "1d",
  "data": [],
  "message": "US.FAKECODE 暂无日线数据，请等待历史数据导入完成"
}
```

### 2. `ktype` 支持三个周期

`Query(pattern="^(1d|4h|1w)$")`——初版文档只写了 `1d|1w`，**现已有 `4h`**。

⚠️ **`4h` 的 `date` 字段返回 Unix 时间戳（秒，int）**，而 `1d`/`1w` 返回 `'YYYY-MM-DD'` 字符串。这是为了让 lightweight-charts 正确显示时间轴。

### 3. `breakdown` 结构为 `{score, raw, ratio}`

初版的 `{score, triggered}` / `{score, value, triggered}` **已废弃**。当前每个因子返回三元组：

```json
{
  "US.AAPL": {
    "date": "2026-10-09",
    "total_score": 78,
    "signal": "BUY",
    "breakdown": {
      "weekly_rsi":      {"score": 22.0, "raw": 28.3,  "ratio": 0.861},
      "daily_macd_pct":  {"score": 16.4, "raw": 0.182, "ratio": 0.818},
      "boll_position":   {"score": 9.9,  "raw": 0.34,  "ratio": 0.66},
      "daily_rsi":       {"score": 18.7, "raw": 23.9,  "ratio": 0.935},
      "weekly_macd_pct": {"score": 5.2,  "raw": 0.48,  "ratio": 0.52},
      "drawdown":        {"score": 11.0, "raw": 0.197, "ratio": 0.735}
    }
  }
}
```

- `ratio` 为归一化后的 0~1 触发强度，`score = ratio × WEIGHTS[因子]`
- 因子键名固定 6 个，与 `scorer.py` 的 `WEIGHTS` 字典一一对应
- 无数据时 `raw` / `ratio` 均为 `null` / `0`
- **总分另有「大盘温度加成」**，因此 6 个因子 `score` 之和可能小于 `total_score`

### 4. 标的池已从 JSON 迁移到 SQLite

- 初版数据源 `watchlist.json` / `config.WATCHLIST_DETAIL` **已废弃**
- 现由 `watchlist_storage.py` 管理 `watchlist` 表，提供完整 CRUD
- `GET /api/watchlist` 支持 `category` / `status` / `market` / `search` 四个筛选参数
- 单只标的详情用 `GET /api/watchlist/{code}`；`has_data` 字段表示该标的在 `kline_indicators` 中是否已有数据

---

## 响应数据格式（示例）

### `GET /api/indicators?code=HK.00700&ktype=1d&days=60`

```json
{
  "code": "HK.00700",
  "ktype": "1d",
  "data": [
    {
      "date": "2026-02-14",
      "open": 398.0, "high": 405.0, "low": 396.0, "close": 402.0,
      "volume": 12340000,
      "ma5": 399.2, "ma10": 397.8, "ma20": 394.1, "ma60": 385.3,
      "ma120": 375.0, "ma200": 368.2, "ma250": 358.0,
      "rsi6": 58.1, "rsi12": 54.2, "rsi24": 51.7,
      "dif": 2.31, "dea": 1.85, "macd": 0.92,
      "boll_upper": 418.5, "boll_mid": 394.1, "boll_lower": 369.7,
      "vol_ma20": 11200000,
      "ema5": 400.1, "ema10": 398.4, "ema15": 396.9,
      "ema20": 395.2, "ema25": 393.8, "ema30": 392.1,
      "atr14": 8.6
    },
    { "date": "2026-02-17", "...": "..." }
  ]
}
```

> ⚠️ 指标列是 **`rsi6` / `rsi12` / `rsi24` 三周期**，**没有 `rsi14`**；均线含 `ma200`。

### `GET /api/scores/latest?code=US.AAPL&date=2026-10-09`

- 带 `date` 查询指定交易日评分（走 `query_score_by_date`），不传则返回最新
- 结构与上节 `breakdown` 示例一致

### `GET /api/watchlist?category=mag7`

返回 SQLite `watchlist` 表中的记录 + 派生字段 `has_data`：

```json
[
  {
    "code": "US.NVDA",
    "name": "NVIDIA Corporation",
    "market": "US",
    "category": "mag7",
    "tags": ["AI芯片", "GPU"],
    "has_data": true
  }
]
```

---

## 前端图表集成建议

### 推荐图表库

| 库 | 适合场景 | 说明 |
|----|---------|------|
| `lightweight-charts` | TradingView 风格 | 项目实际使用；专为金融图表设计，性能优秀。**4h 周期需传 Unix 时间戳** |
| `echarts` | React/Vue 通用 | 内置 K 线图、折线、柱状，配置灵活 |
| `recharts` | React 项目 | 通用图表，金融场景需自定义较多 |

### 消费示例

```javascript
const res = await fetch('/api/indicators?code=HK.00700&ktype=1d&days=60')
const { data, message } = await res.json()
if (!data.length) { showEmpty(message); return }

const klineData = data.map(d => ({ time: d.date, open: d.open, high: d.high, low: d.low, close: d.close }))
const ma20  = data.map(d => ({ time: d.date, value: d.ma20 }))
const rsi   = data.map(d => ({ time: d.date, value: d.rsi12 }))   // 注意：不是 rsi14
```

---

## 历史沿革（v2.0 初版设计 → 现状）

| 维度 | v2.0 初版设计 | 当前实现 |
|------|--------------|---------|
| 端点数 | 4 个 | 37 个业务端点（+1 健康检查） |
| 无数据响应 | HTTP 404 + message | HTTP 200 + `{data: null, message}` |
| `breakdown` 结构 | `{score, triggered}` | `{score, raw, ratio}` |
| 标的池存储 | `watchlist.json` / `config.WATCHLIST_DETAIL` | SQLite `watchlist` 表（`watchlist_storage.py`） |
| CORS | 仅 `GET` | 全方法 + 全 header |
| 指标列 | `rsi14` | `rsi6` / `rsi12` / `rsi24` |
| `ktype` | `1d` / `1w` | `1d` / `4h` / `1w` |
| 只读保证 | 全部只读 | `/api/position`、`/api/allocation` 依赖本机 OpenD |
| 鉴权 | 无 | 无（仍全开放） |
