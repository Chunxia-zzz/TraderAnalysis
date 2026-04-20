# Part C — API 服务层（api_server.py）

> API 层将存储层的数据暴露为 HTTP 接口，供前端图表组件消费。它只做读取，不调用 Futu SDK，不做任何计算，可以独立于后端运行。

---

## 功能清单

| # | 接口 | 方法 | 用途 |
|---|------|------|------|
| J1 | `/api/indicators` | GET | 返回某标的某周期最近 N 根 K 线 + 全部指标（绘图用） |
| J2 | `/api/indicators/latest` | GET | 返回最新一根指标值（面板/信号灯展示） |
| J3 | `/api/scores/latest` | GET | 返回最新评分结果（评分面板展示） |
| J4 | `/api/watchlist` | GET | 返回所有已入库标的列表（下拉选择） |

---

## 实现思路

- 使用 **FastAPI** 框架：轻量、自带 Swagger 文档（`/docs`）
- 所有接口只读 SQLite，调用 `storage.py` 的查询函数
- 不连接 Futu OpenD，不依赖后端进程
- 开发阶段允许跨域（CORS `*`），生产环境应限制 `allow_origins`

---

## 具体实现方案

### api_server.py（自实现，依赖 FastAPI + storage.py）

```python
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import storage

app = FastAPI(title="Strategy Indicators API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # 开发阶段允许所有来源
    allow_methods=["GET"],
)

@app.get("/api/indicators")
def get_indicators(
    code:  str,
    ktype: str = Query(default="1d", pattern="^(1d|1w)$"),
    days:  int = Query(default=60, ge=1, le=500),
):
    """
    J1: 返回某标的某周期最近 N 根 K 线 + 全部指标。
    日期升序返回（最旧在前，最新在后），符合图表从左到右的时间轴。
    """
    rows = storage.query_range(code, ktype, days)
    return {"code": code, "ktype": ktype, "data": rows}


@app.get("/api/indicators/latest")
def get_latest(
    code:  str,
    ktype: str = Query(default="1d", pattern="^(1d|1w)$"),
):
    """J2: 返回最新一根的所有指标值。"""
    return storage.query_latest(code, ktype)


@app.get("/api/scores/latest")
def get_latest_score(code: str):
    """J3: 返回最新一次评分结果。"""
    return storage.query_latest_score(code)


@app.get("/api/watchlist")
def get_watchlist():
    """J4: 返回所有已入库标的列表。"""
    return storage.list_codes()
```

### 启动命令

```bash
pip install fastapi uvicorn
uvicorn api_server:app --host 0.0.0.0 --port 8000

# Swagger 文档地址：http://localhost:8000/docs
```

---

## 响应数据格式

### J1: `GET /api/indicators?code=HK.00700&ktype=1d&days=60`

```json
{
  "code": "HK.00700",
  "ktype": "1d",
  "data": [
    {
      "date": "2026-02-14",
      "open": 398.0, "high": 405.0, "low": 396.0, "close": 402.0,
      "volume": 12340000,
      "ma5": 399.2, "ma10": 397.8, "ma20": 394.1, "ma60": 385.3, "ma120": 375.0, "ma250": 358.0,
      "rsi14": 54.2,
      "dif": 2.31, "dea": 1.85, "macd": 0.92,
      "boll_upper": 418.5, "boll_mid": 394.1, "boll_lower": 369.7,
      "vol_ma20": 11200000
    },
    { "date": "2026-02-17", "...": "..." }
  ]
}
```

### J2: `GET /api/indicators/latest?code=HK.00700&ktype=1d`

```json
{
  "code": "HK.00700",
  "ktype": "1d",
  "date": "2026-04-14",
  "close": 412.0,
  "ma5": 408.2, "ma10": 405.1, "ma20": 394.1, "ma60": 385.3, "ma120": 375.0, "ma250": 358.0,
  "rsi14": 54.2,
  "dif": 2.31, "dea": 1.85, "macd": 0.92,
  "boll_upper": 418.5, "boll_mid": 394.1, "boll_lower": 369.7,
  "vol_ma20": 11200000
}
```

### J3: `GET /api/scores/latest?code=US.AAPL`

```json
{
  "code": "US.AAPL",
  "date": "2026-04-14",
  "total_score": 78,
  "signal": "BUY",
  "breakdown": {
    "weekly_rsi":            {"score": 22, "value": 28.3, "triggered": true},
    "daily_macd_divergence": {"score": 0,  "triggered": false},
    "vix":                   {"score": 12, "value": 32.1, "triggered": true},
    "boll_lower":            {"score": 10, "value": 395.0, "triggered": true},
    "daily_rsi":             {"score": 0,  "value": 42.1, "triggered": false},
    "cnn_fg":                {"score": 10, "value": 18.0, "triggered": true},
    "panic_volume":          {"score": 8,  "triggered": true},
    "weekly_macd_shrink":    {"score": 6,  "triggered": true},
    "ma250_deviation":       {"score": 6,  "value": 0.092, "triggered": true}
  }
}
```

### J4: `GET /api/watchlist`

```json
["HK.00700", "SH.600519", "US.AAPL", "US.TSLA"]
```

前端直接消费以上 JSON，无需任何额外计算。

---

## 前端图表集成建议

### 推荐图表库

| 库 | 适合场景 | 说明 |
|----|---------|------|
| `echarts` | React/Vue 通用 | 内置 K 线图、折线、柱状，配置灵活 |
| `lightweight-charts` | TradingView 风格 | 专为金融图表设计，性能优秀 |
| `recharts` | React 项目 | 通用图表，金融场景需自定义较多 |

### ECharts 消费示例

```javascript
const res = await fetch('/api/indicators?code=HK.00700&ktype=1d&days=60')
const { data } = await res.json()

// K 线主图
const klineData = data.map(d => [d.open, d.close, d.low, d.high])
const dates     = data.map(d => d.date)

// MA 叠加线
const ma5  = data.map(d => d.ma5)
const ma20 = data.map(d => d.ma20)

// RSI 副图
const rsi = data.map(d => d.rsi14)

// MACD 副图
const dif  = data.map(d => d.dif)
const dea  = data.map(d => d.dea)
const macd = data.map(d => d.macd)
```
