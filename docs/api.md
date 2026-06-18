# TraderAnalysis API 文档

> 最后更新：2026-06-18
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
| `allow_methods` | `["*"]` | 允许所有 HTTP 方法（GET/POST 等） |
| `allow_headers` | `["*"]` | 允许任意请求头（含 Authorization） |

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
| GET | `/api/watchlist` | 标的池列表（支持筛选） | 标的选择器 |
| GET | `/api/watchlist/{code}` | 单只标的详情 | 标的详情页 |
| POST | `/api/watchlist` | 新增标的（自动填充富途信息） | 管理页 |
| PATCH | `/api/watchlist/{code}` | 修改标的可编辑字段 | 管理页 |
| DELETE | `/api/watchlist/{code}` | 删除标的 | 管理页 |
| POST | `/api/watchlist/batch` | 批量新增 | 管理页 |
| POST | `/api/watchlist/refresh-snapshot` | 刷新静态快照字段 | 管理页 |
| GET | `/api/stock-filter/search` | 条件选股（需 OpenD） | 选股页 |
| GET | `/api/stock-filter/info` | 单股信息查询 | 选股页 |
| ~~GET~~ | ~~`/api/fundamental/latest`~~ | ~~单标的基本面数据+评分~~ **已停用**（Yahoo Finance 中国不可用） | - |
| ~~GET~~ | ~~`/api/fundamental/overview`~~ | ~~全标的基本面速览~~ **已停用** | - |
| GET | `/api/market-temperature` | 市场温度评分（3 维度综合），附 GLD/BTC 单资产温度 | **MarketTemperature.vue** |
| GET | `/api/market-temperature/history` | 近 N 天市场温度历史 | **MarketTemperature.vue（趋势图）** |
| GET | `/api/asset-temperature/history` | 单资产（GLD/BTC）历史温度评分序列（实时计算） | **MarketTemperature.vue（黄金/比特币趋势图）** |
| GET | `/api/tp-sl` | 止盈止损自动计算（ATR+支撑/阻力） | 前端待接入 |
| GET | `/api/backtest/run` | 信号回测（单股策略验证） | **Backtest.vue** |
| GET | `/api/grid/status` | 网格交易运行状态 | **GridTrading.vue** |
| GET | `/api/grid/orders` | 网格交易记录 | **GridTrading.vue** |

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
      "ma5": 399.2, "ma10": 397.8, "ma20": 394.1, "ma60": 385.3, "ma120": 375.0, "ma200": 365.0, "ma250": 358.0,
      "rsi6": 54.2, "rsi12": 50.1, "rsi24": 48.5,
      "dif": 2.31, "dea": 1.85, "macd": 0.92,
      "boll_upper": 418.5, "boll_mid": 394.1, "boll_lower": 369.7,
      "vol_ma20": 11200000,
      "ema5": 401.2, "ema10": 398.5, "ema15": 396.1, "ema20": 393.8, "ema25": 391.5, "ema30": 389.2
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
  "rsi6": 54.2, "rsi12": 50.1, "rsi24": 48.5,
  "dif": 2.31,
  "dea": 1.85,
  "macd": 0.92,
  "boll_upper": 418.5,
  "boll_mid": 394.1,
  "boll_lower": 369.7,
  "vol_ma20": 11200000,
  "ema5": 401.2, "ema10": 398.5, "ema15": 396.1, "ema20": 393.8, "ema25": 391.5, "ema30": 389.2,
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
  "date": "2026-05-08",
  "total_count": 41,
  "strong_buy": [
    {"code": "US.MCD", "date": "2026-05-08", "total_score": 93.4, "signal": "STRONG_BUY",
     "above_ma5": false, "close": 275.75, "ma5": 280.1, "momentum_score": 9,
     "ema_ribbon": "red"}
  ],
  "buy": [
    {"code": "US.ASTS", "date": "2026-05-08", "total_score": 70.4, "signal": "BUY",
     "above_ma5": true, "close": 75.05, "ma5": 68.68, "momentum_score": 45,
     "ema_ribbon": "green"}
  ],
  "no_action": [
    {"code": "US.MU", "date": "2026-05-08", "total_score": 2.7, "signal": "NO_ACTION",
     "above_ma5": true, "close": 746.81, "ma5": 680.2, "momentum_score": 100,
     "ema_ribbon": "mixed"}
  ],
  "actionable": [
    {"code": "US.ASTS", "date": "2026-05-08", "total_score": 70.4, "signal": "BUY",
     "above_ma5": true, "close": 75.05, "ma5": 68.68, "momentum_score": 45,
     "ema_ribbon": "green"}
  ],
  "momentum_leaders": [
    {"code": "US.MU", "date": "2026-05-08", "total_score": 2.7, "signal": "NO_ACTION",
     "above_ma5": true, "close": 746.81, "ma5": 680.2, "momentum_score": 100},
    {"code": "US.SNDK", "date": "2026-05-08", "total_score": 0.6, "signal": "NO_ACTION",
     "above_ma5": true, "close": 1562.34, "ma5": 1394.89, "momentum_score": 95}
  ],
  "summary": {
    "strong_buy_count": 1,
    "buy_count": 4,
    "no_action_count": 36,
    "actionable_count": 1,
    "momentum_leaders_count": 16
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
| `strong_buy` | 强烈买入（≥80分）的标的列表 |
| `buy` | 建议买入（60~79分）的标的列表 |
| `no_action` | 观望（<60分）的标的列表 |
| `actionable` | **可执行机会**：同时满足 BUY/STRONG_BUY + 站上MA5（确认反转） |
| `momentum_leaders` | **主升浪龙头**：动量评分≥70 的标的，按动量分降序 |
| `summary` | 各分组数量统计 |

**每个标的新增字段（v2.9+）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `above_ma5` | bool\|null | 收盘价是否站上 MA5（确认止跌反转） |
| `close` | float\|null | 最新收盘价 |
| `ma5` | float\|null | MA5 值 |
| `momentum_score` | int\|null | 动量/趋势强度评分 0-100 |

**前端展示建议：**

- **抄底机会区**：展示 `actionable` 列表（评分高 + 站上MA5 = 可执行）
- **主升浪区**：展示 `momentum_leaders` 列表（趋势追涨标的）
- `above_ma5=true` 的 BUY/STRONG_BUY 标的用绿色高亮
- `momentum_score>=70` 用火焰/火箭图标标识

**前端对接建议**

- 新增"机会速览"页面或 Dashboard 顶部卡片区
- 用 3 个区块/颜色分组展示：红色(STRONG_BUY) / 橙色(BUY) / 灰色(NO_ACTION)
- 加日期选择器可切换历史日期
- 点击标的跳转到该标的的详细评分页（调用 `/api/scores/latest?code=XXX&date=XXX`）
- 通用设计：接口只返回 code/score/signal，不关心评分具体怎么算，后续改评分规则不影响

---

### GET `/api/watchlist`

> **v2.6 变更**：数据来源从 `watchlist.json` 改为 SQLite `watchlist` 表，支持筛选参数。

返回标的池列表，支持按分类/状态/市场/关键词筛选。

**请求参数**

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `category` | query | `string` | 按分类过滤（如 `mag7`） |
| `status` | query | `string` | 按状态过滤: `watching` / `holding` / `exited` |
| `market` | query | `string` | 按市场过滤: `US` / `HK` |
| `search` | query | `string` | 模糊搜索 ticker/name/notes |

**响应 200**

```json
{
  "total": 40,
  "categories": { "mag7": "MAG7", "storage": "存储" },
  "watchlist": [
    {
      "code": "US.NVDA",
      "ticker": "NVDA",
      "name": "NVIDIA Corporation",
      "market": "US",
      "category": "mag7",
      "status": "watching",
      "tags": ["AI芯片", "GPU"],
      "target_price": null,
      "forward_pe": null,
      "trailing_pe": null,
      "market_cap": null,
      "current_price": null,
      "thesis": "",
      "notes": "",
      "recommended_strategy": "swing",
      "has_data": true,
      "created_at": "2026-05-06T00:00:00",
      "updated_at": "2026-05-06T00:00:00"
    }
  ]
}
```

**`recommended_strategy` 字段说明（v3.1+）：**

基于历史回测自动推荐的最优策略，可通过 `PATCH /api/watchlist/{code}` 手动修改。

| 值 | 含义 | 适合标的 | 回测参数 |
|-----|------|---------|---------|
| `hold_10d` | 买入持有10天 | 稳健大票(AAPL/SPY) | mode=hold, holding_days=10 |
| `hold_20d` | 买入持有20天 | 中长线标的(GOOGL/TSLA) | mode=hold, holding_days=20 |
| `swing` | 波段操作(恐慌买→恢复卖) | 周期性回调股(NVDA/MU/MCD) | mode=swing, threshold=60, exit_threshold=30 |
| `trend_ma5` | 趋势跟踪(止跌买+跌破MA5卖) | 高弹性成长股(AMD/INTC) | mode=trend, trail_ma=ma5, entry_confirm=above_ma5 |
| `trend_ma10` | 趋势跟踪(止跌买+跌破MA10卖) | 强势主线(META/IBIT) | mode=trend, trail_ma=ma10, entry_confirm=above_ma5 |
| `trend_ma20` | 趋势跟踪(止跌买+跌破MA20卖) | 长趋势(SNDK/MSTR/BABA) | mode=trend, trail_ma=ma20, entry_confirm=above_ma5 |

**前端展示建议：**
- 标的列表中用标签/颜色区分策略类型
- 点击标的时可用 `recommended_strategy` 对应参数自动填充回测面板
- 提供修改入口（下拉选择），调用 `PATCH /api/watchlist/{code} {"recommended_strategy": "trend_ma10"}`

---

### GET `/api/watchlist/{code}`

查询单只标的详情。

**Path Parameter:** `code` — Futu 格式代码（如 `US.AAPL`）

**响应 200:** 完整标的字段（同列表中的单条结构）

**不存在时:** `{"data": null, "message": "Stock US.XXXX not found in watchlist"}`

---

### POST `/api/watchlist`（admin）

新增标的。自动从富途获取基础信息（name、sector、industry 等）。OpenD 离线时降级为手动填充。

**Request Body:**
```json
{
  "code": "US.PLTR",
  "category": "cloud",
  "tags": ["AI", "data"],
  "thesis": "Data analytics leader",
  "target_price": 30.0
}
```

**必填:** `code`

**响应 201:** `{"message": "Stock US.PLTR added to watchlist", "data": {...}}`

**已存在:** `{"data": null, "message": "Stock US.PLTR already exists in watchlist"}`

---

### PATCH `/api/watchlist/{code}`（admin）

修改标的可编辑字段（部分更新，只传需要改的字段）。

**可修改字段:** category, status, tags, target_price, stop_loss, analyst_target_mean, morningstar_fair_value, forward_pe, forward_eps, peg_ratio, revenue_growth, earnings_growth, profit_margin, roe, debt_to_equity, thesis, notes

**不可修改（返回 400）:** code, ticker, name, market, sector, industry, listing_date, trailing_pe, market_cap, current_price, dividend_yield, beta, created_at

**Request Body:**
```json
{"notes": "Q2 下调预期", "forward_pe": 25.0}
```

**响应 200:** `{"message": "Stock US.AAPL updated", "data": {...}, "updated_fields": ["notes", "forward_pe"]}`

---

### DELETE `/api/watchlist/{code}`（admin）

删除标的（仅从 watchlist 移除，不删历史 K 线/评分数据）。

**响应 200:** `{"message": "Stock US.PLTR removed from watchlist"}`

---

### POST `/api/watchlist/batch`（admin）

批量新增标的。

**Request Body:**
```json
{"codes": ["US.PLTR", "US.SNOW"], "category": "cloud", "tags": ["AI"]}
```

**响应 200:** `{"message": "2 stocks added, 0 skipped", "added": [...], "skipped": [...]}`

---

### POST `/api/watchlist/refresh-snapshot`（admin）

刷新标的静态快照字段（trailing_pe, market_cap, current_price 等）。需要 OpenD。

**Query Parameter:** `code`（可选，不传则刷新全部）

**响应 200:** `{"message": "Refreshed 40 stocks", "updated": 38, "failed": [...]}`

---

### GET `/api/stock-filter/search`

条件选股（需 OpenD 在线）。

**请求参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `market` | `string` | 市场（默认 `US`） |
| `min_market_cap` | `float` | 最小市值（亿美元） |
| `max_pe` | `float` | 最大市盈率 |
| `min_price` | `float` | 最低股价 |
| `sector` | `string` | 行业板块 |

**响应 200:** `{"total": 15, "results": [{code, name, market_cap, trailing_pe, current_price, in_watchlist}, ...]}`

**OpenD 离线:** `{"data": null, "message": "Futu OpenD not connected"}`

---

### GET `/api/stock-filter/info`

单股信息查询（新增前预览）。需 OpenD。

**请求参数:** `code`（必填）

**响应 200:** `{code, ticker, name, market, sector, industry, listing_date, market_cap, trailing_pe, current_price, ...}`

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

**v3.5 新增字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `gld_temp` | object\|null | 黄金（GLD）单资产温度评分，实时计算；数据不足时为 `null` |
| `btc_temp` | object\|null | 比特币（IBIT）单资产温度评分，实时计算；数据不足时为 `null` |

`gld_temp` / `btc_temp` 结构：

```json
{
  "label": "黄金",
  "code": "US.GLD",
  "composite_score": 24.3,
  "market_status": "偏悲观",
  "action_suggestion": "积极加仓",
  "price": 312.45,
  "daily_rsi": 38.2,
  "weekly_rsi": 42.1,
  "ma200_dev": 0.0612,
  "ath_drawdown": 0.0381,
  "pos_52w": 0.712,
  "daily_tech_score": 22.1,
  "weekly_tech_score": 28.5,
  "price_score": 18.6,
  "note": null
}
```

| 字段 | 说明 |
|------|------|
| `composite_score` | 综合温度 0~100 |
| `daily_tech_score` | 日线技术面维度（50%） |
| `weekly_tech_score` | 周线技术面维度（35%） |
| `price_score` | 价格位置维度（15%） |
| `ma200_dev` | MA200 偏离度（正=价格高于MA200） |
| `ath_drawdown` | 距历史最高价回撤（0=在ATH） |
| `pos_52w` | 52周位置（0=52w低，1=52w高） |
| `note` | 资产特殊说明（BTC 会提示"IBIT 历史样本有限"） |

> **阈值差异**：黄金 ATH 回撤零分线 25%（正常回调幅度大），MA200 偏离映射区间 ±20%；BTC 零分线 50%，映射区间 ±60%。

**无数据时（HTTP 200）**：`{"data": null, "message": "暂无市场温度数据，请先运行 trader-analysis temperature 命令"}`

---

### GET `/api/asset-temperature/history`

返回单资产（黄金 / 比特币）历史温度评分序列，用于趋势图。

> **注意**：接口实时滑窗计算，每次请求需遍历 N 个交易日逐一评分，响应时间约 1~2 秒。

**请求参数**

| 参数 | 位置 | 类型 | 默认值 | 约束 | 说明 |
|------|------|------|--------|------|------|
| `asset` | query | `string` | **必填** | `GLD` \| `BTC` | 资产 key |
| `days` | query | `integer` | `60` | 1 ≤ days ≤ 365 | 返回最近 N 个交易日 |

**响应 200**

```json
{
  "asset": "GLD",
  "history": [
    {"date": "2026-04-10", "composite_score": 31.2},
    {"date": "2026-04-11", "composite_score": 28.4},
    {"date": "2026-04-14", "composite_score": 22.7}
  ]
}
```

**数据不足时**：返回空数组 `{"asset": "GLD", "history": []}`

**前端调用示例**

```javascript
// trader.js
export const getAssetTemperatureHistory = (asset, days = 60) =>
  client.get('/api/asset-temperature/history', { params: { asset, days } })
```

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

## 信号回测

### GET `/api/backtest/run`

信号回测引擎，支持三种策略模式验证历史收益。

**请求参数**

| 参数 | 类型 | 默认值 | 约束 | 说明 |
|------|------|--------|------|------|
| `code` | string | **必填** | Futu格式 | 股票代码，如 `US.SNDK` |
| `mode` | string | `hold` | `hold`/`swing`/`trend`/`ribbon_long`/`ribbon_short` | 策略模式 |
| `threshold` | integer | `40` | 1-100 | 买入评分阈值 |
| `holding_days` | integer | `10` | 1-250 | [hold] 固定持有天数 |
| `exit_threshold` | integer | `30` | 1-100 | [swing] 评分回落卖出阈值 |
| `max_holding_days` | integer | `120` | 1-500 | [swing/trend] 最大持有天数 |
| `trail_ma` | string | `ma5` | `ma5`/`ma10`/`ma20` | [trend] 跟踪止盈均线 |
| `entry_confirm` | string | `none` | `none`/`above_ma5` | 买入确认：none=立即买, above_ma5=等站上MA5再买 |
| `cooldown` | string | `holding` | `none`/`holding`/`custom` | 冷却期策略 |
| `cooldown_days` | integer | — | 1-250 | [custom] 自定义冷却天数 |
| `start_date` | string | — | YYYY-MM-DD | 回测起始日 |
| `end_date` | string | — | YYYY-MM-DD | 回测截止日 |

**五种模式说明：**

| 模式 | 入场条件 | 出场条件 | 方向 | 适合场景 |
|------|---------|---------|------|---------|
| `hold` | 评分≥threshold | 固定持有N天后卖出 | 多头 | 验证信号质量 |
| `swing` | 评分≥threshold | 评分回落≤exit_threshold | 多头 | 情绪波段（恐慌买→恢复卖） |
| `trend` | 评分≥threshold | 收盘价跌破trail_ma | 多头 | 强势股趋势跟踪 |
| `ribbon_long` | EMA飘带空转多（ema5上穿ema30） | EMA飘带多转空（ema5下穿ema30） | 多头 | 大市值长牛股趋势确认，无需阈值参数 |
| `ribbon_short` | EMA飘带多转空（ema5下穿ema30） | EMA飘带空转多（ema5上穿ema30） | 空头 | 验证做空飘带策略，收益率=(入场价-出场价)/入场价 |

> `ribbon_long`/`ribbon_short` 模式不使用 `threshold` 参数，信号完全由 EMA 飘带翻转驱动。

**响应 200（有数据）：**

```json
{
  "code": "US.SNDK",
  "mode": "trend",
  "params": {
    "mode": "trend",
    "threshold": 40,
    "holding_days": null,
    "exit_threshold": null,
    "max_holding_days": 120,
    "trail_ma": "ma10",
    "cooldown": "holding",
    "start_date": "2025-05-05",
    "end_date": "2026-05-08"
  },
  "summary": {
    "total_signals": 20,
    "completed_trades": 18,
    "win_count": 11,
    "loss_count": 7,
    "win_rate": 61.1,
    "avg_return_pct": 16.06,
    "median_return_pct": 2.90,
    "max_return_pct": 161.88,
    "min_return_pct": -20.33,
    "total_return_pct": 289.10,
    "avg_holding_days": 8.5,
    "sharpe_like": 0.36,
    "profit_factor": 7.05
  },
  "trades": [
    {
      "signal_date": "2025-12-17",
      "entry_price": 206.83,
      "exit_date": "2026-02-10",
      "exit_price": 541.64,
      "return_pct": 161.88,
      "holding_days": 36,
      "entry_score": 60.7,
      "exit_score": null,
      "exit_reason": "below_ma10",
      "signal": "BUY",
      "status": "complete"
    }
  ]
}
```

**响应 200（无数据）：**

```json
{
  "data": null,
  "message": "US.SNDK 暂无评分数据"
}
```

**前端对接要点：**

- `params` 中不适用当前模式的字段为 `null`（如 hold 模式下 `exit_threshold=null`）
- `trades[].exit_reason` 取值：`hold`（固定天数）/ `score_drop`（评分回落）/ `below_ma5`/`below_ma10`/`below_ma20`（跌破均线）/ `max_holding`（超时强制卖出）/ `incomplete`（数据不足）
- `status="incomplete"` 的交易不计入 summary 统计
- 前端建议用 Tab 切换三种模式，每个模式展示对应参数输入框

---

## 止盈止损

### GET `/api/tp-sl`

基于 ATR（波动率）+ 支撑/阻力位（技术面）的混合算法，自动计算止盈止损价位。

**请求参数**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `code` | string | 是 | - | 标的代码（Futu 格式，如 `US.AAPL`） |
| `atr_multiplier` | float | 否 | 2.0 | ATR 止损乘数（0.5~5.0） |
| `min_rr_ratio` | float | 否 | 2.0 | 最低风险回报比（1.0~10.0） |

**成功响应**

```json
{
  "code": "US.NVDA",
  "current_price": 219.44,
  "date": "2026-05-11",
  "atr14": 6.76,
  "stop_loss": {
    "price": 205.92,
    "method": "atr",
    "atr_stop": 205.92,
    "support_stop": 204.69,
    "support_type": "ma20",
    "distance_pct": 0.0616
  },
  "take_profit": {
    "price": 246.48,
    "method": "rr_ratio",
    "rr_target": 246.48,
    "resistance_target": null,
    "resistance_type": null,
    "distance_pct": 0.1232
  },
  "risk_reward_ratio": 2.0,
  "risk_per_share": 13.52,
  "reward_per_share": 27.04,
  "support_levels": {
    "ma20": 204.69,
    "ma60": 189.17,
    "boll_lower": 190.45,
    "swing_low_nearest": 194.74,
    "swing_low_strongest": 164.27
  },
  "resistance_levels": {
    "boll_upper": 218.92,
    "swing_high_nearest": 216.82,
    "swing_high_strongest": 216.82
  },
  "position_sizing": {
    "risk_1pct_of_10k": 7
  },
  "timestamp": "2026-05-12 21:13:59"
}
```

**无数据时**

```json
{"data": null, "message": "US.GDXU 暂无日线数据，请等待历史数据导入完成"}
```

**算法说明**

- **止损** = max(ATR止损, 支撑位止损) — 取较紧者，保证不低于波动率底线
- **止盈** = min(阻力位, R:R目标) — 取较保守者，阻力位优先
- **支撑候选**：MA20、MA60、布林下轨、近期 swing low
- **阻力候选**：布林上轨、近期 swing high
- **仓位建议**：以 $10,000 账户、1% 最大风险计算建议股数

---

## 网格交易

### GET `/api/grid/status`

查看网格交易引擎运行状态。

**请求参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `config_id` | integer（必填） | 网格配置 ID |

**响应 200：**

```json
{
  "config_id": 1,
  "code": "US.GLD",
  "status": "running",
  "env": "simulate",
  "params": {
    "price_upper": 260.0,
    "price_lower": 240.0,
    "grid_count": 10,
    "grid_spacing": 2.0,
    "order_qty": 10,
    "max_position": 100
  },
  "state": {
    "current_position": 30,
    "cost_basis": 245.20,
    "daily_pnl": 42.50,
    "daily_trades": 6,
    "last_price": 248.50,
    "grid_status": {"0":"bought","1":"bought","2":"bought","3":"empty","4":"empty"}
  },
  "grid_lines": [240.0, 242.0, 244.0, 246.0, 248.0, 250.0, 252.0, 254.0, 256.0, 258.0, 260.0]
}
```

### GET `/api/grid/orders`

查看网格交易历史记录。

**请求参数**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `config_id` | integer | **必填** | 网格配置 ID |
| `limit` | integer | `50` | 返回条数（1-500） |

**响应 200：**

```json
{
  "total": 128,
  "orders": [
    {
      "id": 128,
      "config_id": 1,
      "code": "US.GLD",
      "env": "simulate",
      "direction": "SELL",
      "grid_level": 4,
      "grid_price": 248.0,
      "order_qty": 10,
      "order_id": "123456",
      "fill_price": 248.05,
      "fill_qty": 10,
      "status": "filled",
      "pnl": 28.50,
      "triggered_at": "2026-05-06 14:23:15",
      "filled_at": "2026-05-06 14:23:16"
    }
  ]
}
```

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
