# TraderAnalysis API 文档

> 最后更新：2026-04-23
> 协议：HTTP/1.1，响应格式：`application/json`，编码：UTF-8

## 策略数据服务（futu_strategy/api_server.py）

> Base URL（本地开发）：`http://localhost:8000`
> 数据来源：SQLite 数据库（`data/indicators.db`），由 `init_history.py` / `daily_update.py` 写入
> 特点：**不依赖 Futu OpenD**，只要数据库有数据即可独立运行

### 启动

```bash
# 通过 CLI
trader-analysis serve --host 0.0.0.0 --port 8000

# 或直接 uvicorn
uvicorn trader_analysis.futu_strategy.api_server:app --host 0.0.0.0 --port 8000
```

Swagger UI：`http://localhost:8000/docs`

---

## 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/indicators` | 某标的某周期最近 N 根 K 线 + 全部指标 |
| GET | `/api/indicators/latest` | 最新一根的所有指标值 |
| GET | `/api/scores/latest` | 最新一次评分结果 |
| GET | `/api/watchlist` | 完整标的池（含分类、标签、数据状态） |

---

## 通用约定

- 日期字段统一为 `YYYY-MM-DD` 格式字符串
- 数值字段在无法计算时（如指标预热期不足）返回 `null`
- 查询无数据的标的返回 HTTP 404 + `message` 字段描述原因

---

## 接口详情

### GET `/api/indicators`

返回某标的某周期最近 N 根 K 线 + 全部技术指标（日期升序，供图表使用）。

**请求参数**

| 参数 | 位置 | 类型 | 默认值 | 约束 | 说明 |
|------|------|------|--------|------|------|
| `code` | query | `string` | — | 必填 | 标的代码，如 `US.AAPL` |
| `ktype` | query | `string` | `"1d"` | `1d` \| `1w` | K 线周期 |
| `days` | query | `integer` | `60` | 1 ≤ days ≤ 500 | 返回最近 N 根 |

**响应 200**

```json
{
  "code": "US.AAPL",
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
    }
  ]
}
```

**响应 404**（标的无数据）

```json
{
  "code": "US.FAKECODE",
  "ktype": "1d",
  "data": [],
  "message": "US.FAKECODE 暂无日线数据，请等待历史数据导入完成"
}
```

---

### GET `/api/indicators/latest`

返回最新一根 K 线的全部指标值。

**请求参数**

| 参数 | 位置 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `code` | query | `string` | — | 必填，标的代码 |
| `ktype` | query | `string` | `"1d"` | `1d` \| `1w` |

**响应 200**：返回完整 K 线 + 指标 dict

**响应 404**：`{"message": "US.FAKECODE 暂无数据，请等待历史数据导入完成"}`

---

### GET `/api/scores/latest`

返回某标的最新一次评分结果。

**请求参数**

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `code` | query | `string` | 必填，标的代码 |

**响应 200**

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

**响应 404**：`{"message": "US.FAKECODE 暂无评分数据"}`

---

### GET `/api/watchlist`

返回完整标的池，数据来源为 `data/watchlist.json`。

**请求参数**：无

**响应 200**

```json
{
  "categories": {
    "mag7": "MAG7",
    "storage": "存储",
    "crypto": "加密"
  },
  "watchlist": [
    {
      "ticker": "NVDA",
      "name": "NVIDIA Corporation",
      "market": "US",
      "category": "mag7",
      "tags": ["AI芯片", "GPU"],
      "futu_code": "US.NVDA",
      "has_data": true
    }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `categories` | 分类 ID → 中文名映射 |
| `has_data` | `true` = 已有历史数据可查询，`false` = 尚未导入 |

---

## 错误格式

| HTTP 状态码 | 含义 |
|------------|------|
| `200` | 成功 |
| `404` | 标的无数据（返回 `message` 字段） |
| `422` | 请求参数校验失败（FastAPI 标准格式） |
