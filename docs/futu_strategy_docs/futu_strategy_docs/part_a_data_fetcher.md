# Part A — 数据获取（data_fetcher.py / external_data.py）

> 本模块负责从外部获取所有原始数据，供 indicators.py 计算指标、scorer.py 评分使用。

---

## 功能清单

| # | 功能 | 所属文件 | 数据来源 |
|---|------|---------|---------|
| A1 | 获取日线 K 线（250 根） | `data_fetcher.py` | 富途 `request_history_kline` |
| A2 | 获取周线 K 线（60 根） | `data_fetcher.py` | 富途 `request_history_kline` |
| A3 | 获取 VIX 恐慌指数 | `external_data.py` | 富途 `get_market_snapshot` |
| A4 | 获取 CNN 恐惧贪婪指数 | `external_data.py` | CNN HTTP 接口 |

---

## 实现思路

- A1/A2 通过 Futu SDK 调用历史 K 线接口，返回标准 OHLCV DataFrame
- A3 通过 Futu 快照接口获取 VIX 当前价格
- A4 通过 HTTP 请求获取 CNN F&G 评分（0~100，越小越恐慌）
- VIX 和 CNN F&G 是市场级数据（与个股无关），每次运行只获取一次，模块级缓存复用

---

## 具体实现方案

### A1/A2 — K 线数据（`data_fetcher.py`）

**数据来源**：富途 OpenAPI（外部数据）

| 数据 | K 线类型 | 根数 | 用途 |
|------|---------|------|------|
| 日线 | `KLType.K_DAY` | 1000（初始化）/ 按需（增量） | RSI/MACD/BB/MA120/MA250/成交量 |
| 周线 | `KLType.K_WEEK` | 200（初始化）/ 按需（增量） | 周线 RSI/MACD |

**关键代码：**

```python
ret, df, _ = quote_ctx.request_history_kline(
    code=code,
    ktype=KLType.K_DAY,      # 日线；周线改为 KLType.K_WEEK
    autype=AuType.QFQ,        # 前复权
    max_count=1000,            # 初始化取上限 1000；增量更新只拉新增部分
)
# 返回 DataFrame：time_key, open, close, high, low, volume, turnover
```

**额度检查（调用前必须执行）：**

```python
ret, data = quote_ctx.get_history_kl_quota(get_detail=False)
# 确认剩余额度 >= 标的数 × 2（日线+周线各消耗 1 个额度）
```

> 30 天内同一只股票重复请求不会重复扣额度。

---

### A3 — VIX 恐慌指数（`external_data.py`）

**数据来源**：富途 OpenAPI 快照接口（外部数据）

```python
ret, df = quote_ctx.get_market_snapshot(['US.VIX'])
vix_value = float(df['last_price'].iloc[0])
```

**备选方案**：若 `US.VIX` 不可用，改用 `US.VIXY`（VIX 相关 ETF）。

**缓存**：VIX 是市场级数据，同一次运行中多个标的共用一次查询结果。

---

### A4 — CNN Fear & Greed 指数（`external_data.py`）

**数据来源**：CNN 非官方 HTTP 接口（外部数据）

```
GET https://production.dataviz.cnn.io/index/fearandgreed/graphdata
Headers: User-Agent: Mozilla/5.0
返回 JSON → fear_and_greed.score（0~100，越小越恐慌）
```

**异常处理：**
- `timeout=10` 秒
- 网络失败时返回 `None`，该项得 0 分，不中断流程
- 可在 `config.py` 配置代理

**备用方案**：CNN 网页抓取（`BeautifulSoup`），接口失效时启用。

**缓存**：CNN F&G 每天更新一次，模块级变量 `_fg_cache` 缓存：

```python
_fg_cache = None  # 同次运行所有标的共用
```
