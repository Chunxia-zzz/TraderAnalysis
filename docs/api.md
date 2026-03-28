# TraderAnalysis API 文档

> 最后更新：2026-03-28
> Base URL（本地开发）：`http://localhost:8000`
> 协议：HTTP/1.1，响应格式：`application/json`，编码：UTF-8

---

## 浏览器快速调试

本地启动服务后（`python run.py`），直接在浏览器地址栏粘贴以下 URL：

| URL | 说明 |
|-----|------|
| http://localhost:8000/health | 服务状态与上次刷新时间 |
| http://localhost:8000/v1/indicators/latest | 最新一根 bar 的 OHLCV + 全部指标 |
| http://localhost:8000/v1/indicators/history?limit=20 | 最近 20 根 bar 的历史数据 |
| http://localhost:8000/v1/indicators/history?limit=58 | 全量 mock 数据（58 根日K） |
| http://localhost:8000/v1/signals/latest | 最新交易信号（BUY / SELL / HOLD） |
| http://localhost:8000/docs | Swagger UI — 可交互式发送请求 |
| http://localhost:8000/redoc | ReDoc — 只读格式的接口文档 |

---

## 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 服务健康检查 |
| GET | `/v1/indicators/latest` | 最新一根 bar 的 OHLCV + 指标值 |
| GET | `/v1/indicators/history` | 历史 bar 序列（含指标） |
| GET | `/v1/signals/latest` | 最新一根 bar 的交易信号 |

---

## 认证

当前版本无认证。生产部署时建议在反向代理层（Nginx/Caddy）添加 API Key 或 mTLS。

---

## 通用约定

- 时间戳字段统一为 **ISO 8601 UTC** 字符串，如 `"2026-03-28T09:30:00+00:00"`。
- 数值字段在无法计算时（如指标预热期不足）返回 `null`，而非 `0` 或省略字段。
- 所有错误响应遵循统一结构（见[错误格式](#错误格式)）。

---

## 接口详情

### GET `/health`

检查服务是否正常运行及上次数据刷新时间。

**请求参数**：无

**响应 200**

```json
{
  "status": "ok",
  "last_refresh_utc": "2026-03-28T01:05:00.123456+00:00",
  "history_size": 200,
  "strategy": "ma_cross",
  "symbol": "HK.00700",
  "timeframe": "1D",
  "refresh_seconds": 5.0,
  "data_path": "examples/sample_ohlcv.csv"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | `string` | 固定为 `"ok"` |
| `last_refresh_utc` | `string \| null` | 上次成功刷新时间（UTC ISO 8601），启动后首次刷新前为 `null` |
| `history_size` | `integer` | 当前缓存的 bar 数量 |
| `strategy` | `string` | 当前运行的策略名称 |
| `symbol` | `string` | 当前标的代码 |
| `timeframe` | `string` | K 线周期，如 `"1D"`、`"60M"` |
| `refresh_seconds` | `number` | 数据刷新间隔（秒） |
| `data_path` | `string` | 当前数据源路径（CSV 模式下有效） |

**响应 503**：服务启动中，尚未完成首次刷新。

---

### GET `/v1/indicators/latest`

返回最新一根 bar 的 OHLCV 原始数据及所有已计算指标值。

**请求参数**：无

**响应 200**

```json
{
  "timestamp": "2026-03-27T00:00:00",
  "symbol": "HK.00700",
  "timeframe": "1D",
  "open": 395.2,
  "high": 401.0,
  "low": 393.5,
  "close": 399.6,
  "volume": 18234500.0,
  "sma_20": 387.4,
  "sma_60": 371.2,
  "ema_12": 392.1,
  "ema_26": 381.3,
  "rsi_14": 62.4,
  "macd_line": 10.8,
  "macd_signal": 9.2,
  "macd_hist": 1.6,
  "atr_14": 8.3,
  "bb_mid_20": 387.4,
  "bb_upper_20": 408.1,
  "bb_lower_20": 366.7
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp` | `string` | bar 时间戳 |
| `symbol` | `string` | 标的代码，如 `"HK.00700"`、`"US.AAPL"` |
| `timeframe` | `string` | K 线周期 |
| `open/high/low/close` | `number` | OHLC 价格 |
| `volume` | `number` | 成交量（股/手） |
| `sma_N` | `number \| null` | N 周期简单移动均线 |
| `ema_N` | `number \| null` | N 周期指数移动均线 |
| `rsi_14` | `number \| null` | 14 周期 RSI，范围 0–100 |
| `macd_line` | `number \| null` | MACD 线（EMA12 - EMA26） |
| `macd_signal` | `number \| null` | MACD 信号线（9 周期 EMA） |
| `macd_hist` | `number \| null` | MACD 柱（line - signal） |
| `atr_14` | `number \| null` | 14 周期真实波幅均值 |
| `bb_mid_20` | `number \| null` | 布林带中轨（20 周期 SMA） |
| `bb_upper_20` | `number \| null` | 布林带上轨（中轨 + 2σ） |
| `bb_lower_20` | `number \| null` | 布林带下轨（中轨 - 2σ） |

**响应 503**：数据尚未就绪（服务刚启动或刷新失败）。

```json
{ "detail": "No indicator data yet." }
```

---

### GET `/v1/indicators/history`

返回最近 N 根 bar 的历史数据序列（含指标），按时间升序排列。

**请求参数**

| 参数 | 位置 | 类型 | 默认值 | 约束 | 说明 |
|------|------|------|--------|------|------|
| `limit` | query | `integer` | `100` | 1 ≤ limit ≤ 1000 | 返回最近 N 根 bar |

**示例请求**

```
GET /v1/indicators/history?limit=50
```

**响应 200**

```json
[
  {
    "timestamp": "2026-01-02T00:00:00",
    "symbol": "HK.00700",
    "timeframe": "1D",
    "open": 370.0,
    "high": 375.5,
    "low": 368.0,
    "close": 373.2,
    "volume": 12300000.0,
    "sma_20": null,
    "rsi_14": null,
    "macd_line": null,
    "...": "..."
  },
  {
    "timestamp": "2026-03-27T00:00:00",
    "...": "..."
  }
]
```

响应为数组，字段结构与 `/v1/indicators/latest` 相同。预热期不足时指标字段为 `null`。

**响应 422**：`limit` 超出范围。

```json
{
  "detail": [
    {
      "loc": ["query", "limit"],
      "msg": "ensure this value is greater than or equal to 1",
      "type": "value_error.number.not_ge"
    }
  ]
}
```

---

### GET `/v1/signals/latest`

返回最新一根 bar 基于当前策略计算出的交易信号。

**请求参数**：无

**响应 200**

```json
{
  "timestamp": "2026-03-27T00:00:00",
  "symbol": "HK.00700",
  "signal": "BUY",
  "reason": "ema_12 crossed above ema_26"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp` | `string` | 产生信号的 bar 时间戳 |
| `symbol` | `string` | 标的代码 |
| `signal` | `"BUY" \| "SELL" \| "HOLD"` | 信号类型 |
| `reason` | `string` | 信号触发原因（人类可读） |

**响应 503**：数据尚未就绪。

```json
{ "detail": "No signal data yet." }
```

---

## 错误格式

所有 4xx/5xx 响应均返回以下结构：

```json
{ "detail": "错误描述" }
```

FastAPI 参数校验错误（422）返回数组形式的 `detail`，结构遵循 [Pydantic ValidationError 规范](https://docs.pydantic.dev/latest/concepts/validation_errors/)。

| HTTP 状态码 | 含义 |
|------------|------|
| `200` | 成功 |
| `422` | 请求参数校验失败 |
| `503` | 服务数据未就绪（启动中或刷新失败） |

---

## 规划中的接口变更

以下接口**尚未实现**，待 `FutuDataProvider` 接入后同步上线：

### 多标的支持（计划）

```
GET /v1/indicators/latest?symbols=HK.00700,US.AAPL,HK.09988
```

响应改为以 symbol 为 key 的 map：

```json
{
  "HK.00700": { "timestamp": "...", "close": 399.6, "rsi_14": 62.4, "..." },
  "US.AAPL":  { "timestamp": "...", "close": 213.5, "rsi_14": 55.1, "..." }
}
```

### 快照行情（计划）

```
GET /v1/quote/snapshot?symbols=HK.00700,US.AAPL
```

返回实时价格、涨跌幅、成交量，直接透传富途 OpenD 快照数据，不经过指标计算层。

---

## 本地启动

```bash
# 安装依赖
pip install -e .

# 启动（默认读取 examples/sample_ohlcv.csv）
uvicorn trader_analysis.api.app:app --reload

# 接入富途实时行情（OpenD 运行后）
TA_DATA_SOURCE=futu TA_SYMBOLS=HK.00700,US.AAPL uvicorn trader_analysis.api.app:app --reload
```

交互式 API 文档（Swagger UI）：`http://localhost:8000/docs`
ReDoc：`http://localhost:8000/redoc`
