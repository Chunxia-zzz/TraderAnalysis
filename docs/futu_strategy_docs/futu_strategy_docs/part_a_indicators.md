# Part A — 指标计算（indicators.py）

> 本模块是纯计算层，接收 OHLCV DataFrame，追加技术指标列后返回。不感知标的、不感知周期、不做阈值判断。

---

## 功能清单

| # | 指标 | 输入 | 输出列 | 实现方式 |
|---|------|------|--------|---------|
| B1 | MA（移动平均） | close | ma5, ma10, ma20, ma60, ma120, **ma200**, ma250 | **纯 pandas 自实现** |
| B2 | EMA（多空飘带） | close | ema5~ema30（6列） | 纯 pandas 自实现 |
| B3 | RSI（相对强弱） | close | rsi6, rsi12, rsi24 | 纯 pandas 自实现 |
| B4 | MACD | close | dif, dea, macd | 纯 pandas 自实现 |
| B5 | 布林带 | close | boll_upper, boll_mid, boll_lower | 纯 pandas 自实现 |
| B6 | 成交量均线 | volume | vol_ma20 | pandas `rolling().mean()` |
| B7 | ATR（真实波幅） | high, low, close | atr14 | 自实现（Wilder EWM 平滑） |

> ⚠️ **勘误（2026-10-12）**：本表此前把 B1~B5 的实现方式写成 `pandas-ta` 的 `ta.sma()` / `ta.ema()` / `ta.rsi()` /
> `ta.macd()` / `ta.bbands()`。**本项目没有 `pandas-ta` 依赖** —— `indicators.py:13` 只 import `numpy` / `pandas` / `scipy`，
> 模块 docstring 也明确写着「底层使用 pandas 自实现，**无外部指标库依赖**」。
> 同时 B1 的输出列此前漏了 **`ma200`**（`config.py` 的 `'ma': [5,10,20,60,120,200,250]`，DB 中 `ma200` 列实际存在）。

---

## 实现思路

### 设计原则

| 原则 | 说明 |
|------|------|
| **不感知标的** | 函数只接受 DataFrame，不关心是腾讯还是苹果 |
| **不感知周期** | 传入日线 DataFrame 得日线指标，传入周线得周线指标 |
| **只追加数值列** | 输出是带有新指标列的 DataFrame，不做 `< 30` 这类判断 |
| **判断逻辑归 scorer.py** | `RSI < 30` 是策略判断，属于 `scorer.py` |
| **配置驱动** | 周期、标准差等参数通过 config 字典传入 |

### 层次关系

```
data_fetcher.py  →  indicators.py  →  scorer.py
（拉 K 线 DataFrame）  （追加指标列）    （读指标值，做判断，算分）
```

---

## 具体实现方案

### B1~B5 — 核心函数 `calc_indicators`（纯 pandas 自实现）

> ⚠️ **勘误（2026-10-12）**：本节此前贴了一段以 `import pandas_ta as ta` 开头、调用
> `ta.sma()` / `ta.ema()` / `ta.rsi()` / `ta.macd()` / `ta.bbands()` 的示例代码。
> **那是示意代码，不是本项目的实现** —— 项目既没有 `pandas-ta` 依赖，实际算法也与之不同
> （例如 MACD 柱线要 ×2 对齐富途口径、ATR 用 Wilder EWM）。**为避免继续误导，示例代码已删除。**
>
> **真实实现**请看 [`src/trader_analysis/futu_strategy/indicators.py`](../../../src/trader_analysis/futu_strategy/indicators.py)
> 的 `calc_indicators()`；函数签名与配置结构如下（这部分与代码一致）：

```python
# 实际签名（indicators.py）
def calc_indicators(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    参数：
        df     - 含 open/high/low/close/volume 列的 K 线 DataFrame
        config - 指标配置字典
    返回：
        追加了指标列的 DataFrame（原始列保留）

    注意：
        - MA250 至少需要 250 根 K 线预热（初始化传入 1000 根，增量更新传入 300 根）
        - MACD 至少需要 ~60 根预热
        - 开头的 NaN 属正常现象（预热期）
    """
```

### 指标配置（`config.py` 中维护）

```python
# 日线指标配置（传入 250 根日线）
DAILY_INDICATOR_CONFIG = {
    'ma':     [5, 10, 20, 60, 120, 200, 250],
    'ema':    [5, 10, 15, 20, 25, 30],   # 多空飘带 (MA Ribbon)
    'rsi':    [6, 12, 24],
    'macd':   {'fast': 12, 'slow': 26, 'signal': 9},
    'boll':   {'length': 20, 'std': 2},
    'vol_ma': [20],
    'atr':    [14],                       # 止盈止损 ATR 基准
}

# 周线指标配置（传入 60 根周线）
WEEKLY_INDICATOR_CONFIG = {
    'ema':  [5, 10, 15, 20, 25, 30],   # 多空飘带 (MA Ribbon)
    'rsi':  [6, 12, 24],
    'macd': {'fast': 12, 'slow': 26, 'signal': 9},
    'boll': {'length': 20, 'std': 2},
}
```

### 调用示例（通用性体现）

```python
from config import DAILY_INDICATOR_CONFIG, WEEKLY_INDICATOR_CONFIG
from indicators import calc_indicators

# 港股日线、美股周线 —— 完全相同的函数调用
daily_df  = calc_indicators(raw_daily_df,  DAILY_INDICATOR_CONFIG)
weekly_df = calc_indicators(raw_weekly_df, WEEKLY_INDICATOR_CONFIG)
```

---

### B6 — MACD 柱线底背离检测（自实现，依赖 scipy）

```python
from scipy.signal import find_peaks

def detect_macd_divergence(df: pd.DataFrame, lookback: int = 60, distance: int = 5) -> bool:
    """
    检测最近 lookback 根 K 线内是否存在 MACD 柱线底背离。

    底背离定义：
      价格创新低（low[idx2] < low[idx1]）
      但 MACD 柱线未创新低（macd[idx2] > macd[idx1]）

    前提：df 已经过 calc_indicators 计算，含 'macd' 列。
    返回：True = 背离成立，False = 不成立或数据不足
    """
    recent = df.tail(lookback).copy().reset_index(drop=True)

    if 'macd' not in recent.columns or recent['macd'].isna().all():
        return False

    troughs, _ = find_peaks(-recent['low'].values, distance=distance)

    if len(troughs) < 2:
        return False

    idx1, idx2 = troughs[-2], troughs[-1]
    price_new_low   = recent['low'].iloc[idx2] < recent['low'].iloc[idx1]
    macd_no_new_low = recent['macd'].iloc[idx2] > recent['macd'].iloc[idx1]

    return bool(price_new_low and macd_no_new_low)
```

**参数说明：**
- `lookback=60`：只检测最近 60 根 K 线内的背离
- `distance=5`：两个谷底至少间隔 5 根 K 线

---

### B7 — 恐慌放量后缩量检测（自实现，纯 pandas）

```python
def detect_panic_volume(df: pd.DataFrame, lookback: int = 20, panic_multiplier: float = 2.0) -> bool:
    """
    检测最近 lookback 根 K 线内是否出现恐慌放量后缩量。

    条件一：峰值成交量 > 20 日均量 × panic_multiplier（恐慌放量）
    条件二：峰值后近 3 根均量 < 峰值量 × 0.6（缩量回落）

    前提：df 已经过 calc_indicators 计算，含 'vol_ma20' 列。
    返回：True = 满足条件，False = 不满足或数据不足
    """
    if 'vol_ma20' not in df.columns:
        return False

    recent = df.tail(lookback).copy().reset_index(drop=True)
    peak_pos = recent['volume'].idxmax()

    is_panic = recent['volume'].iloc[peak_pos] > recent['vol_ma20'].iloc[peak_pos] * panic_multiplier

    after_peak = recent['volume'].iloc[peak_pos:]
    is_shrinking = (
        len(after_peak) >= 3 and
        after_peak.tail(3).mean() < recent['volume'].iloc[peak_pos] * 0.6
    )

    return bool(is_panic and is_shrinking)
```

---

## 对外接口汇总

| 函数 | 输入 | 输出 | 调用方 |
|------|------|------|--------|
| `calc_indicators(df, config)` | OHLCV DataFrame + 配置字典 | 追加指标列的 DataFrame | `init_history` / `daily_update` / `storage` |
| `detect_macd_divergence(df)` | 含 `macd` 列的 DataFrame | `bool` | ⚠️ **当前无人调用（死代码）** |
| `detect_panic_volume(df)` | 含 `vol_ma20` 列的 DataFrame | `bool` | ⚠️ **当前无人调用（死代码）** |

> ⚠️ **勘误（2026-10-12）**：本表此前把后两个函数的调用方写成 `scorer`。
> 实测 `scorer.py` **只 import 了 `pandas` 与 `config`**，全文没有任何 `detect_*` 调用
> （`grep -rn "detect_macd_divergence|detect_panic_volume" src/` 除定义处无命中）。
> 两者是 v1 二值评分时代的遗留工具函数，现在**没有接入任何评分路径** —— 保留但未使用。

## 输出列名规范

| 列名 | 来源 | 说明 |
|------|------|------|
| `ma5` ~ `ma250` | MA | 简单移动平均（5/10/20/60/120/200/250） |
| `ema5` ~ `ema30` | EMA | 指数移动平均（5/10/15/20/25/30），用于多空飘带 |
| `rsi6` / `rsi12` / `rsi24` | RSI | 取值 0~100 |
| `dif` | MACD | EMA 快线 − EMA 慢线 |
| `dea` | MACD | DIF 的信号线 |
| `macd` | MACD | 柱线 = (DIF − DEA) × 2 |
| `boll_upper` / `boll_mid` / `boll_lower` | Bollinger | 上轨 / 中轨 / 下轨 |
| `vol_ma20` | 成交量均线 | 20 日均量 |

> `scorer.py` 读取指标值时统一取 `df.iloc[-1]`（最新一行），历史值用于背离检测等复杂逻辑时由对应函数内部处理。
