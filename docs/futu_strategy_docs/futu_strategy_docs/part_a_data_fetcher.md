# Part A — 数据获取（data_fetcher.py）

> 本模块负责从富途 OpenAPI 获取原始 K 线数据，供 indicators.py 计算指标、scorer.py 评分使用。

---

## 功能清单

| # | 功能 | 所属文件 | 数据来源 |
|---|------|---------|---------|
| A1 | 获取日线 K 线（250 根） | `data_fetcher.py` | 富途 `request_history_kline` |
| A2 | 获取周线 K 线（60 根） | `data_fetcher.py` | 富途 `request_history_kline` |

---

## 实现思路

- A1/A2 通过 Futu SDK 调用历史 K 线接口，返回标准 OHLCV DataFrame
- K 线数据写入 SQLite，后续计算指标/评分从 DB 读取，不依赖 OpenD

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
