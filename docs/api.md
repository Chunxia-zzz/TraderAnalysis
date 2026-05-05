# TraderAnalysis API 文档

> 最后更新：2026-05-05
> 协议：HTTP/1.1，响应格式：`application/json`，编码：UTF-8

## 策略数据服务（futu_strategy/api_server.py）

> Base URL（本地开发）：`http://localhost:8000`
> 数据来源：SQLite 数据库（`data/indicators.db`），由 `init_history.py` / `daily_update.py` 写入
> 特点：**不依赖 Futu OpenD**，只要数据库有数据即可独立运行

### 启动

```bash
# 通过 CLI
trader-analysis serve --host 0.0.0.0 --port 8000

# 或直接 uvicorn（开发模式，代码修改后自动重载）
uvicorn trader_analysis.futu_strategy.api_server:app --host 0.0.0.0 --port 8000 --reload --reload-dir src
```

Swagger UI：`http://localhost:8000/docs`

---

## 跨域（CORS）

服务已配置 CORS 中间件：

| 配置项 | 值 | 说明 |
|--------|------|------|
| `allow_origins` | `["*"]` | 允许任意域名跨域请求 |
| `allow_methods` | `["GET"]` | 仅允许 GET 方法 |
| `allow_headers` | `["*"]` | 允许任意请求头 |

前端可直接 `fetch` 调用，无需代理。

---

## 数据更新频率与缓存建议

| 数据 | 更新频率 | 前端缓存建议 |
|------|---------|-------------|
| K 线 + 指标 (`/api/indicators`) | 每日收盘后更新一次（美东 16:00 / 北京 04:00） | 缓存至次日凌晨 |
| 个股评分 (`/api/scores/latest`) | 跟随 `trader-analysis run` 执行 | 同上 |
| 市场温度 (`/api/market-temperature`) | 跟随 `trader-analysis temperature` 执行 | 同上 |
| 标的池 (`/api/watchlist`) | 仅在 `watchlist.json` 编辑后变化 | 可长期缓存 |

> **注意**：周末/节假日不产生新数据，API 返回最近一个交易日的结果。

---

## 概览

| 方法 | 路径 | 说明 | 前端页面 |
|------|------|------|---------|
| GET | `/health` | 健康检查 | App.vue（启动时检测） |
| GET | `/api/indicators` | 某标的某周期最近 N 根 K 线 + 全部指标 | Chart.vue |
| GET | `/api/indicators/latest` | 最新一根的所有指标值 | Dashboard.vue |
| GET | `/api/scores/latest` | 单个标的评分结果（支持指定日期） | Dashboard.vue |
| GET | `/api/scores/overview` | 全标的评分速览（按信号分组） | **机会速览页** |
| GET | `/api/watchlist` | 完整标的池（含分类、标签、数据状态） | 标的选择器 |
| GET | `/api/market-temperature` | 市场温度评分（3 维度综合） | **MarketTemperature.vue** |
| GET | `/api/market-temperature/history` | 近 N 天市场温度历史 | **MarketTemperature.vue（趋势图）** |

---

## 通用约定

- 日期字段统一为 `YYYY-MM-DD` 格式字符串
- 数值字段在无法计算时（如指标预热期不足）返回 `null`
- **所有接口统一返回 HTTP 200**，无数据时通过 `data: null` + `message` 字段表示
- 所有价格、指标值均为 `number`（float），成交量为 `number`（integer）
- 布尔值使用 JSON 原生 `true` / `false`

### 无数据时的统一响应格式（HTTP 200）

```json
{"data": null, "message": "描述性提示文案"}
```

**前端判断逻辑：**

```javascript
const res = await api.get('/api/xxx', { params })
if (res.data.data === null || res.data.message) {
  // 无数据，展示 res.data.message 提示文案
} else {
  // 正常渲染
}
```

> 注意：只有参数校验失败（如 ktype 传了非法值）才返回 HTTP 422。

---

## 接口详情

### GET `/health`

健康检查，前端启动时调用以检测后端是否在线。

**请求参数**：无

**响应 200**

```json
{"status": "ok"}
```

> 前端实现：App.vue 启动时调用，成功显示绿点，失败/超时显示红点。

---

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

**无数据时（HTTP 200）**

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

**响应 200**

```json
{
  "code": "US.AAPL",
  "ktype": "1d",
  "date": "2026-05-01",
  "open": 398.0,
  "high": 405.0,
  "low": 396.0,
  "close": 402.0,
  "volume": 12340000,
  "turnover": 4950000000,
  "ma5": 399.2,
  "ma10": 397.8,
  "ma20": 394.1,
  "ma60": 385.3,
  "ma120": 375.0,
  "ma250": 358.0,
  "rsi14": 54.2,
  "dif": 2.31,
  "dea": 1.85,
  "macd": 0.92,
  "boll_upper": 418.5,
  "boll_mid": 394.1,
  "boll_lower": 369.7,
  "vol_ma20": 11200000,
  "updated_at": "2026-05-01T04:15:00"
}
```

**无数据时（HTTP 200）**：`{"data": null, "message": "US.FAKECODE 暂无数据，请等待历史数据导入完成"}`

---

### GET `/api/scores/latest`

返回某标的最新一次评分结果（个股级抄底信号评分）。

> **v2.3 变更**：评分系统从二值判断改为连续映射（6 维度加权，满分 100）。
> breakdown 字段结构从 `{score, value, triggered}` 改为 `{score, raw, ratio}`。

**请求参数**

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `code` | query | `string` | 必填，标的代码 |
| `date` | query | `string` | 可选，指定日期 `YYYY-MM-DD`。不传则返回最新评分 |

**示例调用**

```
GET /api/scores/latest?code=US.NVDA              → 最新评分
GET /api/scores/latest?code=US.NVDA&date=2026-03-27  → 查看 3月27日的评分
```

**响应 200**

```json
{
  "code": "US.NVDA",
  "date": "2026-05-04",
  "total_score": 39.6,
  "signal": "NO_ACTION",
  "breakdown": {
    "weekly_rsi":       {"score": 4.5,  "raw": 61.0,   "ratio": 0.18},
    "daily_macd_pct":   {"score": 15.3, "raw": 0.234,  "ratio": 0.766},
    "boll_position":    {"score": 7.4,  "raw": 0.506,  "ratio": 0.494},
    "daily_rsi":        {"score": 11.7, "raw": 40.8,   "ratio": 0.584},
    "weekly_macd_pct":  {"score": 0.7,  "raw": 0.926,  "ratio": 0.074},
    "ma250_deviation":  {"score": 0.0,  "raw": -0.128, "ratio": 0.0}
  },
  "updated_at": "2026-05-05 20:30:00"
}
```

**breakdown 字段说明**

| 字段 | 类型 | 说明 |
|------|------|------|
| `score` | float | 该维度实际得分（0 ~ 权重上限） |
| `raw` | float/null | 原始指标值（RSI 值 / 百分位 / %B / 偏离度） |
| `ratio` | float | 归一化比率 0~1（0=无信号，1=最强信号） |

**6 维度定义**

| key | 维度 | 权重 | 满分条件 | raw 含义 |
|-----|------|------|----------|----------|
| `weekly_rsi` | 周线 RSI6 | 25 | RSI≤20 | RSI 原始值 |
| `daily_macd_pct` | 日线 MACD 百分位 | 20 | 百分位=0%(最弱) | 百分位排名(0~1) |
| `boll_position` | 布林带 %B | 15 | %B=0(下轨) | %B 值(0~1) |
| `daily_rsi` | 日线 RSI6 | 20 | RSI≤20 | RSI 原始值 |
| `weekly_macd_pct` | 周线 MACD 百分位 | 10 | 百分位=0%(最弱) | 百分位排名(0~1) |
| `ma250_deviation` | MA250 偏离 | 10 | 偏离≥15% | 偏离度(正=价格低于MA) |

**信号映射**

| 总分区间 | signal | 含义 |
|---------|--------|------|
| ≥ 90 | `STRONG_BUY` | 极度超卖，强烈买入 |
| ≥ 70 | `BUY` | 明显超卖，建议买入 |
| < 70 | `NO_ACTION` | 未达标，观望 |

**前端渲染建议**

- 每个维度用进度条展示 `ratio`（0~1），颜色按 ratio 高低映射
- `total_score` 用大号数字 + 环形图展示
- ratio > 0.7 的维度高亮（表示该因子强烈触发）
- 对比同一标的不同日期的 total_score 变化趋势

**无数据时（HTTP 200）**

```json
// 标的无数据
{"data": null, "message": "US.FAKECODE 暂无评分数据"}

// 指定日期无数据（如非交易日）
{"data": null, "message": "US.SPY 在 2026-04-03 暂无评分数据（可能为非交易日）"}
```

**前端对接建议**

- Dashboard 页面加一个日期选择器（DatePicker），默认不传 date（取最新）
- 用户选择日期后，请求 `/api/scores/latest?code=XXX&date=YYYY-MM-DD`
- 判断逻辑：`if (res.data.data === null)` 展示 message，否则渲染评分
- 同时可配合 `/api/indicators?code=XXX&days=1` 查看当天技术指标
- 评分数据覆盖范围约 2022-09 ~ 至今（取决于 backfill 范围）

---

### GET `/api/scores/overview`

返回所有标的的评分速览，按信号分组、分数降序。用于一眼看清当前有哪些买入机会。

**请求参数**

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `date` | query | `string` | 可选，指定日期 `YYYY-MM-DD`。不传则取各标的最新评分 |

**示例调用**

```
GET /api/scores/overview              → 最新全标的评分速览
GET /api/scores/overview?date=2026-03-27  → 查看暴跌日所有标的评分
```

**响应 200（有数据）**

```json
{
  "date": "2026-03-27",
  "total_count": 40,
  "strong_buy": [
    {"code": "US.META", "date": "2026-03-27", "total_score": 99.7, "signal": "STRONG_BUY"},
    {"code": "US.MSFT", "date": "2026-03-27", "total_score": 96.8, "signal": "STRONG_BUY"},
    {"code": "US.QQQ",  "date": "2026-03-27", "total_score": 90.1, "signal": "STRONG_BUY"}
  ],
  "buy": [
    {"code": "US.SPY",  "date": "2026-03-27", "total_score": 89.4, "signal": "BUY"},
    {"code": "US.NVDA", "date": "2026-03-27", "total_score": 85.2, "signal": "BUY"}
  ],
  "no_action": [
    {"code": "US.KO",   "date": "2026-03-27", "total_score": 12.3, "signal": "NO_ACTION"}
  ],
  "summary": {
    "strong_buy_count": 3,
    "buy_count": 14,
    "no_action_count": 23
  }
}
```

**无数据时（HTTP 200）**

```json
{"data": null, "message": "2026-04-03 暂无评分数据（可能为非交易日）"}
```

**字段说明**

| 字段 | 说明 |
|------|------|
| `date` | 数据对应日期 |
| `total_count` | 有评分数据的标的总数 |
| `strong_buy` | 强烈买入（≥90分）的标的列表，按分数降序 |
| `buy` | 建议买入（70~89分）的标的列表，按分数降序 |
| `no_action` | 观望（<70分）的标的列表，按分数降序 |
| `summary` | 各信号数量统计 |

**前端对接建议**

- 新增"机会速览"页面或 Dashboard 顶部卡片区
- 用 3 个区块/颜色分组展示：红色(STRONG_BUY) / 橙色(BUY) / 灰色(NO_ACTION)
- 加日期选择器可切换历史日期
- 点击标的跳转到该标的的详细评分页（调用 `/api/scores/latest?code=XXX&date=XXX`）
- 通用设计：接口只返回 code/score/signal，不关心评分具体怎么算，后续改评分规则不影响

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

---

### GET `/api/market-temperature`

返回最新一期市场温度评分，供前端仪表盘展示。

> **v2.3 变更**：维度从 6 个精简为 3 个（移除了波动率/量能/避险维度）。
> `vol_score`、`volume_score`、`safe_haven_score`、`gld_price`、`vix_value` 字段保留但固定返回 `null`。
> 前端应只展示非 null 的维度。

**请求参数**：无

**响应 200**

```json
{
  "date": "2026-05-05",
  "composite_score": 82.2,
  "target_position_pct": 24.3,
  "extreme_triggered": false,
  "leverage_tool": "none",
  "daily_tech_score": 76.6,
  "weekly_tech_score": 86.2,
  "vol_score": null,
  "price_score": 91.2,
  "volume_score": null,
  "safe_haven_score": null,
  "spy_price": 718.01,
  "qqq_price": 672.88,
  "gld_price": null,
  "vix_value": null,
  "spy_daily_rsi": 64.5,
  "qqq_daily_rsi": 68.2,
  "spy_weekly_rsi": 72.1,
  "qqq_weekly_rsi": 75.3,
  "spy_ma200_dev": 0.0742,
  "qqq_ma200_dev": 0.1151,
  "spy_vol_ratio": 0.96,
  "qqq_vol_ratio": 0.84,
  "created_at": "2026-05-05 19:43:00",
  "detail": {
    "SPY_RSI": 64.5,
    "SPY_RSI_score": 60.0,
    "SPY_MACD_score": 88.5,
    "SPY_BB_pctB": 0.8,
    "SPY_BB_score": 80.0,
    "QQQ_RSI": 68.2,
    "QQQ_RSI_score": 60.0,
    "QQQ_MACD_score": 91.7,
    "QQQ_BB_pctB": 0.851,
    "QQQ_BB_score": 85.1,
    "SPY_Weekly_RSI": 72.1,
    "SPY_Weekly_RSI_score": 70.0,
    "SPY_Weekly_MACD_score": 90.0,
    "SPY_Weekly_BB_pctB": 0.85,
    "SPY_Weekly_BB_score": 85.0,
    "QQQ_Weekly_RSI": 75.3,
    "QQQ_Weekly_RSI_score": 70.0,
    "QQQ_Weekly_MACD_score": 92.0,
    "QQQ_Weekly_BB_pctB": 0.9,
    "QQQ_Weekly_BB_score": 90.0,
    "SPY_price": 718.01,
    "SPY_52w_score": 96.1,
    "SPY_ATH_drawdown": 0.0095,
    "SPY_ATH_score": 93.7,
    "SPY_MA200_dev": 0.0742,
    "SPY_MA200_score": 74.7,
    "QQQ_price": 672.88,
    "QQQ_52w_score": 98.1,
    "QQQ_ATH_drawdown": 0.0057,
    "QQQ_ATH_score": 96.2,
    "QQQ_MA200_dev": 0.1151,
    "QQQ_MA200_score": 88.4
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `composite_score` | float | 综合评分 0~100（越高越贪婪） |
| `target_position_pct` | float | 建议仓位 10%~120% |
| `extreme_triggered` | bool | 是否触发极端层（杠杆区） |
| `leverage_tool` | string | `none` / `margin` / `margin + OTM_call` |
| `daily_tech_score` | float | 日线技术面维度评分（权重 50%） |
| `weekly_tech_score` | float | 周线技术面维度评分（权重 35%） |
| `price_score` | float | 价格位置维度评分（权重 15%） |
| `vol_score` | null | 已废弃（v2.3 移除波动率维度） |
| `volume_score` | null | 已废弃（v2.3 移除量能维度） |
| `safe_haven_score` | null | 已废弃（v2.3 移除避险维度） |
| `detail` | object | 各子指标评分明细（供调试和前端展示） |

**无数据时（HTTP 200）**：`{"data": null, "message": "暂无市场温度数据，请先运行 trader-analysis temperature 命令"}`

#### 前端渲染映射规则

前端不做计算，只根据 `composite_score` 做查表映射：

**评分 → 市场状态 / 颜色 / 操作建议：**

| 评分区间 | 市场状态 | 颜色 | 背景色 | 操作建议 |
|---------|---------|------|--------|---------|
| 0 ~ 5 | 极端恐慌 | `#1a237e` | `#e8eaf6` | 融资+期权超配 |
| 5 ~ 15 | 极度恐慌 | `#1a5fb4` | `#d0e4f5` | 重仓逆势买入 |
| 15 ~ 30 | 偏悲观 | `#3584e4` | `#dbeafe` | 积极加仓 |
| 30 ~ 45 | 略偏冷 | `#62a0ea` | `#e0f2fe` | 适度加仓 |
| 45 ~ 55 | 中性 | `#9a9996` | `#f5f5f5` | 维持仓位 |
| 55 ~ 70 | 略偏热 | `#ff7800` | `#fff3e0` | 适度减仓 |
| 70 ~ 85 | 偏贪婪 | `#e66100` | `#fbe9e7` | 积极减仓 |
| 85 ~ 100 | 极度贪婪 | `#c01c28` | `#ffebee` | 大幅减仓 |

**杠杆工具文案映射：**

| `leverage_tool` 值 | 显示文案 | 补充说明 |
|-------------------|---------|---------|
| `"none"` | 不显示 | — |
| `"margin"` | 建议融资补仓（现货ETF） | 融资额度不超过净值30%，评分回升至45后偿还 |
| `"margin + OTM_call"` | 建议融资 + OTM Call期权超配 | 融资≤净值30% + 权利金≤净值10%，期权选30-60天轻度OTM |

**维度评分条颜色（通用）：**

| 评分 | 颜色 | 含义 |
|------|------|------|
| 0 ~ 20 | `#1565c0` | 深蓝（恐慌） |
| 20 ~ 40 | `#42a5f5` | 浅蓝 |
| 40 ~ 60 | `#9e9e9e` | 灰色（中性） |
| 60 ~ 80 | `#ff9800` | 橙色 |
| 80 ~ 100 | `#d32f2f` | 红色（贪婪） |

**前端仪表盘布局参考（v2.3 更新 — 3 维度）：**

```
┌─────────────────────────────────────────────────────────┐
│  市场温度仪表盘              更新时间: {created_at}       │
├─────────────────────────────────────────────────────────┤
│  综合评分: ████████████████░░░░  {composite_score} / 100│
│  市场状态: {查表得到的 label}                            │
│  建议仓位: {target_position_pct}%                       │
│  操作建议: {查表得到的 action}                           │
├─────────────────────────────────────────────────────────┤
│  维度拆解:                                              │
│  日线技术面 [50%]  ████████░░░░  {daily_tech_score}     │
│  周线技术面 [35%]  █████████░░░  {weekly_tech_score}    │
│  价格位置  [15%]  ███████░░░░░  {price_score}          │
├────────────────────────┬────────────────────────────────┤
│         SPY            │           QQQ                  │
│  价格: {spy_price}     │  价格: {qqq_price}            │
│  日RSI: {spy_daily_rsi}│  日RSI: {qqq_daily_rsi}       │
│  周RSI: {spy_weekly_rsi}│ 周RSI: {qqq_weekly_rsi}      │
│  MA200: {spy_ma200_dev}│  MA200: {qqq_ma200_dev}       │
└────────────────────────┴────────────────────────────────┘
```

---

### GET `/api/market-temperature/history`

返回近 N 天的市场温度评分历史，用于趋势图。

**请求参数**

| 参数 | 位置 | 类型 | 默认值 | 约束 | 说明 |
|------|------|------|--------|------|------|
| `days` | query | `integer` | `30` | 1 ≤ days ≤ 365 | 返回最近 N 天 |

**响应 200**

```json
{
  "history": [
    {
      "date": "2026-04-30",
      "composite_score": 72.5,
      "target_position_pct": 32.0,
      "extreme_triggered": false,
      "leverage_tool": "none",
      "daily_tech_score": 80.1,
      "weekly_tech_score": 62.3,
      "vol_score": null,
      "price_score": 85.2,
      "volume_score": null,
      "safe_haven_score": null
    }
  ]
}
```

> **前端注意**：`vol_score`、`volume_score`、`safe_haven_score` 固定为 `null`（已废弃维度），前端应跳过 null 值的维度不予渲染。

---

## 响应状态码

| HTTP 状态码 | 含义 |
|------------|------|
| `200` | 成功（含"无数据"情况，通过 `data: null` + `message` 区分） |
| `422` | 请求参数校验失败（如 ktype 传了非法值，FastAPI 标准格式） |

> **v2.3 变更**：所有"无数据"场景从 HTTP 404 改为 HTTP 200 + `{data: null, message: "..."}`。
> 前端不再需要 catch 404 错误，统一在 then 分支处理。

---

## 附录：市场温度字段速查

### 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `date` | string | 数据对应的交易日（YYYY-MM-DD） |
| `composite_score` | float | 综合评分 0~100 |
| `target_position_pct` | float | 建议仓位百分比 10~120 |
| `extreme_triggered` | bool | 极端层是否触发 |
| `leverage_tool` | string | 杠杆工具建议 |
| `daily_tech_score` | float | 日线技术面维度评分（权重 50%） |
| `weekly_tech_score` | float | 周线技术面维度评分（权重 35%） |
| `price_score` | float | 价格位置维度评分（权重 15%） |
| `vol_score` | null | 已废弃 |
| `volume_score` | null | 已废弃 |
| `safe_haven_score` | null | 已废弃 |
| `spy_price` | float | SPY 最新收盘价 |
| `qqq_price` | float | QQQ 最新收盘价 |
| `gld_price` | null | 已废弃 |
| `vix_value` | null | 已废弃 |
| `spy_daily_rsi` | float | SPY 日线 RSI6 |
| `qqq_daily_rsi` | float | QQQ 日线 RSI6 |
| `spy_weekly_rsi` | float | SPY 周线 RSI6 |
| `qqq_weekly_rsi` | float | QQQ 周线 RSI6 |
| `spy_ma200_dev` | float | SPY 相对 MA200 偏离度（如 0.08 = +8%） |
| `qqq_ma200_dev` | float | QQQ 相对 MA200 偏离度 |
| `spy_vol_ratio` | float | SPY 当日量比（volume / vol_ma20） |
| `qqq_vol_ratio` | float | QQQ 当日量比 |
| `created_at` | string | 计算时间 |
| `detail` | object | 完整子指标评分明细（见下表） |

### detail 字段明细（v2.3 — 3 维度）

**维度 1：日线技术面（SPY + QQQ 各 3 项取平均）**

| 键 | 说明 |
|----|------|
| `SPY_RSI` / `QQQ_RSI` | 日线 RSI6 原始值 |
| `SPY_RSI_score` / `QQQ_RSI_score` | RSI 分档评分（每10点一档，<10→0, 10-20→10, ..., >90→100） |
| `SPY_MACD_score` / `QQQ_MACD_score` | MACD histogram 在近 252 天中的百分位 × 100 |
| `SPY_BB_pctB` / `QQQ_BB_pctB` | 布林带 %B 值（0~1，0=下轨，1=上轨） |
| `SPY_BB_score` / `QQQ_BB_score` | %B × 100 |

**维度 2：周线技术面（SPY + QQQ 各 3 项取平均）**

| 键 | 说明 |
|----|------|
| `SPY_Weekly_RSI` / `QQQ_Weekly_RSI` | 周线 RSI6 原始值 |
| `SPY_Weekly_RSI_score` / `QQQ_Weekly_RSI_score` | 周线 RSI 分档评分 |
| `SPY_Weekly_MACD_score` / `QQQ_Weekly_MACD_score` | 周线 MACD 百分位评分（lookback=52） |
| `SPY_Weekly_BB_pctB` / `QQQ_Weekly_BB_pctB` | 周线布林 %B |
| `SPY_Weekly_BB_score` / `QQQ_Weekly_BB_score` | 周线布林评分 |

**维度 3：价格位置（SPY + QQQ 各 3 项取平均）**

| 键 | 说明 |
|----|------|
| `SPY_price` / `QQQ_price` | 当前收盘价 |
| `SPY_52w_score` / `QQQ_52w_score` | 52 周位置评分（0=52w低，100=52w高） |
| `SPY_ATH_drawdown` / `QQQ_ATH_drawdown` | 距 ATH 回撤比例（0=在ATH） |
| `SPY_ATH_score` / `QQQ_ATH_score` | ATH 回撤评分（回撤15%=0分） |
| `SPY_MA200_dev` / `QQQ_MA200_dev` | MA200 偏离度原始值 |
| `SPY_MA200_score` / `QQQ_MA200_score` | MA200 偏离度评分（偏离±15%=0/100） |

---

## 前端对接指南

### 新增 API 调用函数

在 `src/api/trader.js` 中需新增：

```javascript
// 市场温度 — 最新评分
export function getMarketTemperature() {
  return api.get('/api/market-temperature')
}

// 市场温度 — 历史趋势
export function getMarketTemperatureHistory(days = 30) {
  return api.get('/api/market-temperature/history', { params: { days } })
}
```

### 页面：MarketTemperature.vue

**路由**：`/market-temperature`

**页面结构（v2.3 — 3 维度简化版）**：

1. **顶部概览卡片**
   - 综合评分（大字号 + 进度条，颜色按映射表）
   - 市场状态标签（查表得到 label + background-color）
   - 建议仓位百分比
   - 操作建议文案
   - 杠杆工具提示（仅 `leverage_tool !== "none"` 时显示）

2. **维度拆解区（3 行）**
   - 日线技术面 [50%] + 评分条 + 数值
   - 周线技术面 [35%] + 评分条 + 数值
   - 价格位置 [15%] + 评分条 + 数值
   - **注意**：跳过值为 `null` 的维度（vol_score/volume_score/safe_haven_score）

3. **标的指标卡片（2 列：SPY + QQQ）**
   - SPY 卡：价格、日RSI、周RSI、MA200偏离度
   - QQQ 卡：同上
   - **不再展示 GLD 和 VIXY**

4. **历史趋势图**
   - 调用 `/api/market-temperature/history?days=30`
   - X 轴：日期，Y 轴（左）：composite_score，Y 轴（右）：target_position_pct
   - 用 ECharts 折线图渲染

### 数据刷新策略

| 场景 | 行为 |
|------|------|
| 页面加载 | 调用 `getMarketTemperature()` 获取最新 |
| 数据为空（404） | 显示提示"暂无数据，请确认后端已运行 temperature 命令" |
| 自动刷新 | 不需要轮询，数据每日更新一次 |
| 手动刷新 | 可提供一个刷新按钮重新调用接口 |

### 前端无需计算

所有评分、仓位建议、状态标签均由后端完成。前端只做：
1. 调接口拿 JSON
2. 根据 `composite_score` 查映射表得到颜色/文案
3. 渲染 UI

### 完整映射代码参考（JS — v2.3）

```javascript
const TEMPERATURE_LEVELS = [
  { max: 5,   label: '极端恐慌', color: '#1a237e', bg: '#e8eaf6', action: '融资+期权超配' },
  { max: 15,  label: '极度恐慌', color: '#1a5fb4', bg: '#d0e4f5', action: '重仓逆势买入' },
  { max: 30,  label: '偏悲观',   color: '#3584e4', bg: '#dbeafe', action: '积极加仓' },
  { max: 45,  label: '略偏冷',   color: '#62a0ea', bg: '#e0f2fe', action: '适度加仓' },
  { max: 55,  label: '中性',     color: '#9a9996', bg: '#f5f5f5', action: '维持仓位' },
  { max: 70,  label: '略偏热',   color: '#ff7800', bg: '#fff3e0', action: '适度减仓' },
  { max: 85,  label: '偏贪婪',   color: '#e66100', bg: '#fbe9e7', action: '积极减仓' },
  { max: 100, label: '极度贪婪', color: '#c01c28', bg: '#ffebee', action: '大幅减仓' },
]

// v2.3: 只有 3 个维度，按此顺序展示
const DIMENSIONS = [
  { key: 'daily_tech_score',  label: '日线技术面', weight: '50%' },
  { key: 'weekly_tech_score', label: '周线技术面', weight: '35%' },
  { key: 'price_score',       label: '价格位置',   weight: '15%' },
]

function getTemperatureLevel(score) {
  return TEMPERATURE_LEVELS.find(level => score <= level.max)
}

function getDimensionColor(score) {
  if (score <= 20) return '#1565c0'
  if (score <= 40) return '#42a5f5'
  if (score <= 60) return '#9e9e9e'
  if (score <= 80) return '#ff9800'
  return '#d32f2f'
}

const LEVERAGE_LABELS = {
  none: null,
  margin: { text: '建议融资补仓（现货ETF）', detail: '融资额度不超过净值30%' },
  'margin + OTM_call': { text: '建议融资 + OTM Call期权超配', detail: '融资≤净值30% + 权利金≤净值10%' },
}

// 渲染维度时过滤 null 值
function renderDimensions(data) {
  return DIMENSIONS.filter(dim => data[dim.key] !== null)
}
```
