# TraderAnalysis API 文档

> 最后更新：2026-05-04
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
| GET | `/api/scores/latest` | 最新一次评分结果（个股级） | Dashboard.vue |
| GET | `/api/watchlist` | 完整标的池（含分类、标签、数据状态） | 标的选择器 |
| GET | `/api/market-temperature` | 市场温度评分（6 维度综合） | **MarketTemperature.vue（新页面）** |
| GET | `/api/market-temperature/history` | 近 N 天市场温度历史 | **MarketTemperature.vue（趋势图）** |

---

## 通用约定

- 日期字段统一为 `YYYY-MM-DD` 格式字符串
- 数值字段在无法计算时（如指标预热期不足）返回 `null`
- 查询无数据的标的返回 HTTP 404 + `message` 字段描述原因
- 所有价格、指标值均为 `number`（float），成交量为 `number`（integer）
- 布尔值使用 JSON 原生 `true` / `false`

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

---

### GET `/api/market-temperature`

返回最新一期市场温度评分，供前端仪表盘展示。

**请求参数**：无

**响应 200**

```json
{
  "date": "2026-05-01",
  "composite_score": 79.7,
  "target_position_pct": 26.2,
  "extreme_triggered": false,
  "leverage_tool": "none",
  "daily_tech_score": 87.2,
  "weekly_tech_score": 65.0,
  "vol_score": 83.6,
  "price_score": 90.3,
  "volume_score": 52.5,
  "safe_haven_score": 74.1,
  "spy_price": 720.65,
  "qqq_price": 674.15,
  "gld_price": 423.18,
  "vix_value": 27.43,
  "spy_daily_rsi": 71.7,
  "qqq_daily_rsi": 74.9,
  "spy_weekly_rsi": 66.7,
  "qqq_weekly_rsi": 69.4,
  "spy_ma200_dev": 0.0789,
  "qqq_ma200_dev": 0.1182,
  "spy_vol_ratio": 0.8,
  "qqq_vol_ratio": 0.95,
  "created_at": "2026-05-04 04:01:27",
  "detail": {
    "SPY_RSI": 71.7,
    "SPY_RSI_score": 86.1,
    "SPY_MACD_score": 88.5,
    "SPY_BB_pctB": 0.8,
    "SPY_BB_score": 80.0,
    "QQQ_RSI": 74.9,
    "QQQ_RSI_score": 91.5,
    "QQQ_MACD_score": 91.7,
    "QQQ_BB_pctB": 0.851,
    "QQQ_BB_score": 85.1,
    "SPY_Weekly_RSI": 66.7,
    "SPY_Weekly_RSI_score": 77.8,
    "SPY_Weekly_MACD_score": 50.0,
    "QQQ_Weekly_RSI": 69.4,
    "QQQ_Weekly_RSI_score": 82.3,
    "QQQ_Weekly_MACD_score": 50.0,
    "VIXY_price": 27.43,
    "VIXY_pct_rank": 0.164,
    "VIXY_pct_score": 83.6,
    "SPY_52w_score": 97.6,
    "SPY_ATH_drawdown": 0.0058,
    "SPY_ATH_score": 97.1,
    "SPY_MA200_dev": 0.0789,
    "SPY_MA200_score": 69.7,
    "QQQ_52w_score": 99.1,
    "QQQ_ATH_drawdown": 0.0027,
    "QQQ_ATH_score": 98.7,
    "QQQ_MA200_dev": 0.1182,
    "QQQ_MA200_score": 79.6,
    "GLD_RSI": 43.2,
    "GLD_RSI_score": 61.3,
    "GLD_MACD_score": 78.3,
    "GLD_BB_pctB": 0.172,
    "GLD_BB_score": 82.8
  }
}
```

| 字段 | 说明 |
|------|------|
| `composite_score` | 综合评分 0~100（越高越贪婪） |
| `target_position_pct` | 建议仓位 10%~120% |
| `extreme_triggered` | 是否触发极端层（杠杆区） |
| `leverage_tool` | `none` / `margin` / `margin + OTM_call` |
| `detail` | 各子指标评分明细（供调试和前端展示） |

**响应 404**：`{"message": "暂无市场温度数据，请先运行 trader-analysis temperature 命令"}`

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

**前端仪表盘布局参考：**

```
┌─────────────────────────────────────────────────────────┐
│  📊 市场温度仪表盘          更新时间: {created_at}       │
├─────────────────────────────────────────────────────────┤
│  综合评分: ████████████████░░░░  {composite_score} / 100│
│  市场状态: {查表得到的 label}                            │
│  建议仓位: {target_position_pct}%                       │
│  操作建议: {查表得到的 action}                           │
├─────────────────────────────────────────────────────────┤
│  维度拆解:                                              │
│  日线技术面 [30%]  ████████░░░░  {daily_tech_score}     │
│  周线技术面 [15%]  █████████░░░  {weekly_tech_score}    │
│  波动率    [25%]  ██████████░░  {vol_score}            │
│  价格位置  [15%]  ███████░░░░░  {price_score}          │
│  量能确认   [8%]  █████████░░░  {volume_score}         │
│  避险信号   [7%]  ██████████░░  {safe_haven_score}     │
├──────────┬──────────┬──────────┬────────────────────────┤
│   SPY    │   QQQ    │   GLD    │   VIXY                 │
│ ${spy_price} │ ${qqq_price} │ ${gld_price} │ ${vix_value}│
│ 日RSI {spy_daily_rsi} │ 日RSI {qqq_daily_rsi} │ RSI {detail.GLD_RSI} │ 分位 {detail.VIXY_pct_rank}│
│ 周RSI {spy_weekly_rsi} │ 周RSI {qqq_weekly_rsi} │      │                 │
│ MA200 {spy_ma200_dev} │ MA200 {qqq_ma200_dev} │       │                 │
│ 量比 {spy_vol_ratio}x │ 量比 {qqq_vol_ratio}x │       │                 │
└──────────┴──────────┴──────────┴────────────────────────┘
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
      "vol_score": 75.0,
      "price_score": 85.2,
      "volume_score": 48.5,
      "safe_haven_score": 70.2
    }
  ]
}
```

---

## 错误格式

| HTTP 状态码 | 含义 |
|------------|------|
| `200` | 成功 |
| `404` | 标的/数据无对应记录（返回 `message` 字段） |
| `422` | 请求参数校验失败（FastAPI 标准格式） |

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
| `daily_tech_score` | float | 日线技术面维度评分 |
| `weekly_tech_score` | float | 周线技术面维度评分 |
| `vol_score` | float | 波动率维度评分 |
| `price_score` | float | 价格位置维度评分 |
| `volume_score` | float | 量能确认维度评分 |
| `safe_haven_score` | float | 避险信号维度评分 |
| `spy_price` | float | SPY 最新收盘价 |
| `qqq_price` | float | QQQ 最新收盘价 |
| `gld_price` | float | GLD 最新收盘价 |
| `vix_value` | float | VIXY 最新收盘价 |
| `spy_daily_rsi` | float | SPY 日线 RSI(14) |
| `qqq_daily_rsi` | float | QQQ 日线 RSI(14) |
| `spy_weekly_rsi` | float | SPY 周线 RSI(14) |
| `qqq_weekly_rsi` | float | QQQ 周线 RSI(14) |
| `spy_ma200_dev` | float | SPY 相对 MA200 偏离度（如 0.08 = +8%） |
| `qqq_ma200_dev` | float | QQQ 相对 MA200 偏离度 |
| `spy_vol_ratio` | float | SPY 当日量比（volume / vol_ma20） |
| `qqq_vol_ratio` | float | QQQ 当日量比 |
| `created_at` | string | 计算时间 |
| `detail` | object | 完整子指标明细（见下表） |

### detail 字段明细

| 键 | 说明 |
|----|------|
| `SPY_RSI` / `QQQ_RSI` | 日线 RSI(14) 原始值 |
| `SPY_RSI_score` / `QQQ_RSI_score` | RSI 评分（0~100） |
| `SPY_MACD_score` / `QQQ_MACD_score` | MACD histogram 百分位评分 |
| `SPY_BB_pctB` / `QQQ_BB_pctB` | 布林带 %B 值（0~1） |
| `SPY_BB_score` / `QQQ_BB_score` | 布林带评分 |
| `SPY_Weekly_RSI` / `QQQ_Weekly_RSI` | 周线 RSI(14) 原始值 |
| `SPY_Weekly_RSI_score` / `QQQ_Weekly_RSI_score` | 周线 RSI 评分 |
| `SPY_Weekly_MACD_score` / `QQQ_Weekly_MACD_score` | 周线 MACD 百分位评分 |
| `VIXY_price` | VIXY 收盘价 |
| `VIXY_pct_rank` | VIXY 在近 252 天中的百分位（0~1） |
| `VIXY_pct_score` | 波动率评分（反转后 0~100） |
| `SPY_52w_score` / `QQQ_52w_score` | 52 周位置评分 |
| `SPY_ATH_drawdown` / `QQQ_ATH_drawdown` | 距 ATH 回撤比例（0=在ATH） |
| `SPY_ATH_score` / `QQQ_ATH_score` | ATH 回撤评分 |
| `SPY_MA200_dev` / `QQQ_MA200_dev` | MA200 偏离度原始值 |
| `SPY_MA200_score` / `QQQ_MA200_score` | MA200 偏离度评分 |
| `SPY_vol_ratio` / `QQQ_vol_ratio` | 量比原始值 |
| `SPY_vol_ratio_score` / `QQQ_vol_ratio_score` | 量比评分 |
| `SPY_vol_trend_score` / `QQQ_vol_trend_score` | 5 日量能趋势评分 |
| `GLD_RSI` | GLD 日线 RSI(14) |
| `GLD_RSI_score` | GLD RSI 反向评分 |
| `GLD_MACD_score` | GLD MACD 反向百分位评分 |
| `GLD_BB_pctB` | GLD 布林 %B |
| `GLD_BB_score` | GLD BB 反向评分 |

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

### 新增页面：MarketTemperature.vue

**路由建议**：`/market-temperature`

**页面结构**：

1. **顶部概览卡片**
   - 综合评分（大字号 + 进度条，颜色按映射表）
   - 市场状态标签（查表得到 label + background-color）
   - 建议仓位百分比
   - 操作建议文案
   - 杠杆工具提示（仅 `leverage_tool !== "none"` 时显示）

2. **维度拆解区**
   - 6 行，每行：维度名称 + 权重标签 + 评分条（Progress bar，颜色按维度评分条映射）+ 数值

3. **标的指标卡片（4 列）**
   - SPY 卡：价格、日RSI、周RSI、MA200偏离度、量比
   - QQQ 卡：同上
   - GLD 卡：价格、RSI
   - VIXY 卡：价格、百分位排名

4. **历史趋势图**（可选）
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

### 完整映射代码参考（JS）

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
```
