# Part A — 评分系统（scorer.py）

> 本模块从 indicators.py 的计算结果中读取数值，做阈值判断并加权评分，输出 0~100 总分和交易信号。

---

## 功能清单

| # | 评分项 | 权重 | 触发条件 | 数据来源 |
|---|--------|-----|---------|---------|
| C1 | 周线 RSI 超卖 | 22 分 | `weekly_rsi14 < 30` | indicators 计算结果 |
| C2 | 日线 MACD 柱线底背离 | 16 分 | `detect_macd_divergence() == True` | indicators 判断函数 |
| C3 | VIX 恐慌指数高位 | 12 分 | `vix > 30` | external_data（外部数据） |
| C4 | 布林带下轨附近 | 10 分 | `close <= boll_lower × 1.02` | indicators 计算结果 |
| C5 | 日线 RSI 超卖 | 10 分 | `daily_rsi14 < 30` | indicators 计算结果 |
| C6 | CNN 恐惧贪婪指数极低 | 10 分 | `fg_score < 25` | external_data（外部数据） |
| C7 | 恐慌放量后缩量 | 8 分 | `detect_panic_volume() == True` | indicators 判断函数 |
| C8 | 周线 MACD 柱线缩小 | 6 分 | 柱线为负且 `abs(最新) < abs(前一根)` | indicators 计算结果 |
| C9 | 价格偏离 MA250 超 8% | 6 分 | `(ma250 - close) / ma250 > 0.08` | indicators 计算结果 |
| | **合计** | **100 分** | | |

---

## 实现思路

- scorer.py **不做任何指标计算**，只做"读值 → 比较阈值 → 打分"
- C1/C4/C5/C8/C9 从 DataFrame 最新行直接读取指标值与阈值比较
- C2 调用 `indicators.detect_macd_divergence(daily_df)`
- C7 调用 `indicators.detect_panic_volume(daily_df)`
- C3（VIX）和 C6（CNN F&G）由调用方从 `external_data.py` 获取后作为参数传入
- 每个评分项独立判断，互不影响

---

## 具体实现方案

### 评分函数（自实现，读取 indicators 输出 + 外部数据）

```python
import pandas as pd
from indicators import detect_macd_divergence, detect_panic_volume

def calculate_score(code: str, daily_df: pd.DataFrame, weekly_df: pd.DataFrame,
                    vix: float, fg: float | None) -> dict:
    """
    参数：
        code      - 标的代码
        daily_df  - 已经过 calc_indicators() 计算的日线 DataFrame
        weekly_df - 已经过 calc_indicators() 计算的周线 DataFrame
        vix       - VIX 当前值（来自 external_data）
        fg        - CNN F&G 评分（来自 external_data，None 表示获取失败）

    返回：
    {
        "code": "US.AAPL",
        "total_score": 78,
        "signal": "BUY",            # "STRONG_BUY" / "BUY" / "NO_ACTION"
        "breakdown": {
            "weekly_rsi":            {"score": 22, "value": 28.3, "triggered": True},
            "daily_macd_divergence": {"score": 0,  "triggered": False},
            "vix":                   {"score": 12, "value": 32.1, "triggered": True},
            "boll_lower":            {"score": 10, "value": 395.0, "triggered": True},
            "daily_rsi":             {"score": 0,  "value": 42.1, "triggered": False},
            "cnn_fg":                {"score": 10, "value": 18.0, "triggered": True},
            "panic_volume":          {"score": 8,  "triggered": True},
            "weekly_macd_shrink":    {"score": 6,  "triggered": True},
            "ma250_deviation":       {"score": 6,  "value": 0.092, "triggered": True},
        },
        "timestamp": "2026-04-13 16:00:00"
    }
    """
    score = 0
    breakdown = {}

    # 读最新行
    d = daily_df.iloc[-1]
    w = weekly_df.iloc[-1]

    # C1: 周线 RSI < 30（22分）
    triggered = w['rsi14'] < 30 if pd.notna(w.get('rsi14')) else False
    breakdown['weekly_rsi'] = {'score': 22 if triggered else 0, 'value': w.get('rsi14'), 'triggered': triggered}
    if triggered: score += 22

    # C2: 日线 MACD 底背离（16分）
    triggered = detect_macd_divergence(daily_df)
    breakdown['daily_macd_divergence'] = {'score': 16 if triggered else 0, 'triggered': triggered}
    if triggered: score += 16

    # C3: VIX > 30（12分）
    triggered = vix > 30 if vix is not None else False
    breakdown['vix'] = {'score': 12 if triggered else 0, 'value': vix, 'triggered': triggered}
    if triggered: score += 12

    # C4: 布林带下轨附近（10分）
    triggered = d['close'] <= d['boll_lower'] * 1.02 if pd.notna(d.get('boll_lower')) else False
    breakdown['boll_lower'] = {'score': 10 if triggered else 0, 'value': d.get('boll_lower'), 'triggered': triggered}
    if triggered: score += 10

    # C5: 日线 RSI < 30（10分）
    triggered = d['rsi14'] < 30 if pd.notna(d.get('rsi14')) else False
    breakdown['daily_rsi'] = {'score': 10 if triggered else 0, 'value': d.get('rsi14'), 'triggered': triggered}
    if triggered: score += 10

    # C6: CNN F&G < 25（10分）
    triggered = fg < 25 if fg is not None else False
    breakdown['cnn_fg'] = {'score': 10 if triggered else 0, 'value': fg, 'triggered': triggered}
    if triggered: score += 10

    # C7: 恐慌放量后缩量（8分）
    triggered = detect_panic_volume(daily_df)
    breakdown['panic_volume'] = {'score': 8 if triggered else 0, 'triggered': triggered}
    if triggered: score += 8

    # C8: 周线 MACD 柱线缩小（6分）
    if len(weekly_df) >= 2 and pd.notna(w.get('macd')):
        prev_macd = weekly_df.iloc[-2]['macd']
        triggered = w['macd'] < 0 and abs(w['macd']) < abs(prev_macd) if pd.notna(prev_macd) else False
    else:
        triggered = False
    breakdown['weekly_macd_shrink'] = {'score': 6 if triggered else 0, 'triggered': triggered}
    if triggered: score += 6

    # C9: 价格偏离 MA250 > 8%（6分）
    if pd.notna(d.get('ma250')) and d['ma250'] > 0:
        deviation = (d['ma250'] - d['close']) / d['ma250']
        triggered = deviation > 0.08
    else:
        deviation = None
        triggered = False
    breakdown['ma250_deviation'] = {'score': 6 if triggered else 0, 'value': deviation, 'triggered': triggered}
    if triggered: score += 6

    # 信号等级
    if score >= 90:
        signal = 'STRONG_BUY'
    elif score >= 70:
        signal = 'BUY'
    else:
        signal = 'NO_ACTION'

    return {
        'code': code,
        'total_score': score,
        'signal': signal,
        'breakdown': breakdown,
        'timestamp': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
```

---

## 信号等级

| 总分 | 信号 | 动作 |
|------|------|------|
| ≥ 90 | `STRONG_BUY` | 模拟盘买入（较大仓位） |
| 70 ~ 89 | `BUY` | 模拟盘买入（标准仓位） |
| < 70 | `NO_ACTION` | 记录日志，不交易 |

---

## 关键说明

### 周线 MACD 背离 vs 柱线缩小

本策略包含两个独立的 MACD 相关指标，互不干扰：

| 指标 | 数据 | 计算方式 | 权重 |
|------|------|---------|------|
| 日线 MACD 柱线背离（C2） | 日线 | 价格新低但柱线未新低（底背离） | 16 分 |
| 周线 MACD 柱线缩小（C8） | 周线 | 负值柱线最近绝对值变小（空头减弱） | 6 分 |
