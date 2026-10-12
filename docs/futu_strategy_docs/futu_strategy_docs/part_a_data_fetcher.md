# Part A — 数据获取（data_fetcher.py / providers.py）

> 本模块负责从富途 OpenAPI 获取原始 K 线数据，供 indicators.py 计算指标、scorer.py 评分使用。
>
> 源码位置：
> - `src/trader_analysis/futu_strategy/data_fetcher.py` —— **薄封装层**，对外暴露 `fetch_daily` / `fetch_weekly` / `check_kl_quota`
> - `src/trader_analysis/futu_strategy/providers.py` —— **实际请求层**，`FutuLiveDataProvider`

---

## 功能清单

| # | 功能 | 所属文件 | 数据来源 |
|---|------|---------|---------|
| A1 | 获取日线 K 线 | `data_fetcher.fetch_daily()` → `providers.FutuLiveDataProvider.get_daily()` | 富途 `request_history_kline` |
| A2 | 获取周线 K 线 | `data_fetcher.fetch_weekly()` → `providers.FutuLiveDataProvider.get_weekly()` | 富途 `request_history_kline` |
| A3 | 4 小时 K 线 | `providers.FutuLiveDataProvider.get_kline(kl_type=KLType.K_240M)` | 富途 `request_history_kline` |
| A4 | 调用前额度检查 | `data_fetcher.check_kl_quota()` | 富途 `get_history_kl_quota` |
| A5 | OHLCV 列标准化 | `providers.normalize_ohlcv()` | 纯本地处理 |

> ⚠️ **`data_fetcher.py` 不直接调用 `request_history_kline`**，它只做异常包装（把 `DataProviderError` 转成 `RuntimeError`）与配置注入；真正的 SDK 调用在 `providers.py`。

---

## 实现思路

- 通过 Futu SDK 调用历史 K 线接口，返回标准 OHLCV DataFrame
- 拉取后经 `normalize_ohlcv(df, symbol, timeframe)` 标准化列名（遵循 `OHLCVSchema`，如 `time_key` → `timestamp`）
- K 线数据写入 SQLite，后续计算指标/评分从 DB 读取，**不依赖 OpenD**

---

## 具体实现方案

### A1/A2/A3 — K 线数据

**数据来源**：富途 OpenAPI（外部数据）

| 数据 | K 线类型 | 根数（初始化） | 根数（日常/增量） | 用途 |
|------|---------|--------------|-----------------|------|
| 日线 | `KLType.K_DAY` | `config.INIT_DAILY_KLINE_COUNT` = **1000** | `config.DAILY_KLINE_COUNT` = **250** | RSI/MACD/BB/MA200/MA250/成交量 |
| 周线 | `KLType.K_WEEK` | `config.INIT_WEEKLY_KLINE_COUNT` = **200** | `config.WEEKLY_KLINE_COUNT` = **60** | 周线 RSI/MACD、潮汐方向 |
| 4 小时 | `KLType.K_240M` | — | 60（增量，见 daily_update） | 日线以下的短线结构 |

> **为什么日线默认要 250 根**：计算 `MA200` 至少需 200 根，额外 50 根作为缓冲。**只拉 60 根会导致 MA200/MA250 全为 NULL。**

**入口函数：**

```python
def fetch_daily(quote_ctx, code: str) -> pd.DataFrame:
    """根数由 config.DAILY_KLINE_COUNT（250）控制"""
    return _provider.get_daily(quote_ctx, code, count=config.DAILY_KLINE_COUNT)

def fetch_weekly(quote_ctx, code: str) -> pd.DataFrame:
    """根数由 config.WEEKLY_KLINE_COUNT（60）控制"""
    return _provider.get_weekly(quote_ctx, code, count=config.WEEKLY_KLINE_COUNT)
```

### providers.py 的两种拉取模式

```python
ret, df, _ = quote_ctx.request_history_kline(
    code, ktype=KLType.K_DAY, autype=AuType.QFQ
)
# 返回 DataFrame：time_key, open, close, high, low, volume, turnover
```

| 模式 | 触发条件 | 行为 |
|------|---------|------|
| **简单模式** | 不传 `start` | 不传 `max_count`，**Futu 默认返回最近 250 根**（`count` 参数在此模式下不生效） |
| **分段拉取模式** | 传 `start` | 每段 `max_count=1000`，取到最后一根的日期 +1 天作为下段起点，循环至返回 < 250 根为止；段间 `sleep(0.5)` 防限频，最后 `drop_duplicates(subset=["time_key"])` 合并 |

> ⚠️ **重要坑：不传 `start` 时 `max_count` 会被忽略，长历史拉不全。** 要拉超过 250 根的历史必须在 `init_history` 中传 `--start`。

### A4 — 额度检查（调用前必须执行）

```python
ret, quota = quote_ctx.get_history_kl_quota(get_detail=False)
# quota 可能是 tuple (used, remain, detail_list) / DataFrame / dict，check_kl_quota 已做兼容
# 需要额度 = len(code_list) * 2（每标的日线 + 周线各消耗 1 个）
# 不足时抛 RuntimeError，在循环开始前统一检查一次
```

> 30 天内同一只股票重复请求不会重复扣额度。

---

## 与本模块相关的已知数据质量坑

| 坑 | 说明 | 处理 |
|---|---|---|
| **QFQ 复权断层** | 传了 `autype=QFQ`，但 `daily_update` 是增量拉取——QFQ 基准是"最新价"，除权/拆股后全部历史需重算，增量只追加新数据 → 拆股前价格停在旧基准，形成假断层（典型：US.APH 2:1 拆股后 dd60 由 +1.3% 变 −49.3%） | 用 `scripts/refetch_klines.py <code...>` 全量重拉该标的 |
| 富途单次上限 250 根 | 见上文「简单模式」 | 显式传 `start` 走分段拉取 |
| `futu` 启动报 `expected str, not NoneType` | 缺 `APPDATA` 环境变量 | 先 `export APPDATA=...` |
