# Part A — 指标计算（indicators.py）

> 本模块是纯计算层，接收 OHLCV DataFrame，追加技术指标列后返回。不感知标的、不感知周期、不做阈值判断。

---

## 功能清单

| # | 指标 | 输入 | 输出列 | 实现方式 |
|---|------|------|--------|---------|
| B1 | MA（移动平均） | close | ma5, ma10, ma20, ma60, ma120, ma250 | pandas-ta `ta.sma()` |
| B2 | RSI（相对强弱） | close | rsi14 | pandas-ta `ta.rsi()` |
| B3 | MACD | close | dif, dea, macd | pandas-ta `ta.macd()` |
| B4 | 布林带 | close | boll_upper, boll_mid, boll_lower | pandas-ta `ta.bbands()` |
| B5 | 成交量均线 | volume | vol_ma20 | pandas `rolling().mean()` |
| B6 | MACD 柱线底背离 | low + macd | bool | 自实现（依赖 scipy `find_peaks`） |
| B7 | 恐慌放量后缩量 | volume + vol_ma20 | bool | 自实现（纯 pandas） |

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

### B1~B5 — 核心函数 `calc_indicators`（自实现，底层依赖 pandas-ta）

```python
import pandas as pd
import pandas_ta as ta

def calc_indicators(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    通用指标计算函数。

    参数：
        df     - 含 open/high/low/close/volume 列的 K 线 DataFrame
                 由调用方决定标的和周期，本函数完全不感知
        config - 指标配置字典

    返回：
        追加了指标列的 DataFrame（原始列保留）

    注意：
        - MA250 至少需要 250 根 K 线预热（初始化传入 1000 根，增量更新传入 300 根）
        - MACD 至少需要 ~60 根预热
        - 开头的 NaN 属正常现象（预热期）
    """
    df = df.copy()

    # MA（简单移动平均）
    for period in config.get('ma', []):
        df[f'ma{period}'] = ta.sma(df['close'], length=period)

    # EMA（指数移动平均，可选独立输出）
    for period in config.get('ema', []):
        df[f'ema{period}'] = ta.ema(df['close'], length=period)

    # RSI
    for period in config.get('rsi', []):
        df[f'rsi{period}'] = ta.rsi(df['close'], length=period)

    # MACD（柱线 × 2，对齐富途/A 股显示口径）
    if 'macd' in config:
        c = config['macd']
        fast, slow, signal = c['fast'], c['slow'], c['signal']
        macd_df = ta.macd(df['close'], fast=fast, slow=slow, signal=signal)
        df['dif']  = macd_df[f'MACD_{fast}_{slow}_{signal}']
        df['dea']  = macd_df[f'MACDs_{fast}_{slow}_{signal}']
        df['macd'] = macd_df[f'MACDh_{fast}_{slow}_{signal}'] * 2

    # 布林带
    if 'boll' in config:
        c = config['boll']
        length, std = c['length'], c['std']
        boll_df = ta.bbands(df['close'], length=length, std=std)
        df['boll_upper'] = boll_df[f'BBU_{length}_{float(std)}']
        df['boll_mid']   = boll_df[f'BBM_{length}_{float(std)}']
        df['boll_lower'] = boll_df[f'BBL_{length}_{float(std)}']

    # 成交量均线
    for period in config.get('vol_ma', []):
        df[f'vol_ma{period}'] = df['volume'].rolling(window=period).mean()

    return df
```

### 指标配置（`config.py` 中维护）

```python
# 日线指标配置（传入 250 根日线）
DAILY_INDICATOR_CONFIG = {
    'ma':     [5, 10, 20, 60, 120, 250],
    'rsi':    [14],
    'macd':   {'fast': 12, 'slow': 26, 'signal': 9},
    'boll':   {'length': 20, 'std': 2},
    'vol_ma': [20],
}

# 周线指标配置（传入 60 根周线）
WEEKLY_INDICATOR_CONFIG = {
    'rsi':  [14],
    'macd': {'fast': 12, 'slow': 26, 'signal': 9},
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
| `calc_indicators(df, config)` | OHLCV DataFrame + 配置字典 | 追加指标列的 DataFrame | scorer / storage |
| `detect_macd_divergence(df)` | 含 `macd` 列的 DataFrame | `bool` | scorer |
| `detect_panic_volume(df)` | 含 `vol_ma20` 列的 DataFrame | `bool` | scorer |

## 输出列名规范

| 列名 | 来源 | 说明 |
|------|------|------|
| `ma5` ~ `ma250` | MA | 简单移动平均（5/10/20/60/120/250） |
| `rsi14` | RSI | 取值 0~100 |
| `dif` | MACD | EMA 快线 − EMA 慢线 |
| `dea` | MACD | DIF 的信号线 |
| `macd` | MACD | 柱线 = (DIF − DEA) × 2 |
| `boll_upper` / `boll_mid` / `boll_lower` | Bollinger | 上轨 / 中轨 / 下轨 |
| `vol_ma20` | 成交量均线 | 20 日均量 |

> `scorer.py` 读取指标值时统一取 `df.iloc[-1]`（最新一行），历史值用于背离检测等复杂逻辑时由对应函数内部处理。
