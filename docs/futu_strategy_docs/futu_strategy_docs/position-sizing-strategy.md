# 市场仓位管理策略框架

> 版本：v1.0 | 创建日期：2026-04-30
> 数据源：Futu OpenAPI | 评估频率：周频

---

## 1. 策略概述

### 1.1 目标

根据市场技术指标和情绪冷热程度，量化评估当前市场状态，输出建议仓位水平。**用数字约束人性**——恐慌时敢于逆势加仓，贪婪时纪律性减仓只留鱼尾。

### 1.2 核心逻辑

```
市场越恐慌 → 综合评分越低 → 仓位越高（逆势加仓）
市场越贪婪 → 综合评分越高 → 仓位越低（纪律减仓）
```

### 1.3 适用范围

| 项目 | 说明 |
|------|------|
| 投资标的 | 美股权益类（SPY/QQQ 为主） |
| 评估频率 | 每周一次（周日晚/周一盘前） |
| 仓位范围 | 10% ~ 120%（90%以上为杠杆区） |
| 持仓周期 | 中长线（周级别调仓） |

---

## 2. 监控标的与数据源

### 2.1 核心标的

| 标的 | Futu 代码 | 角色 | 说明 |
|------|----------|------|------|
| S&P 500 ETF | `US.SPY` | 大盘代表 | 反映美股整体水温 |
| Nasdaq 100 ETF | `US.QQQ` | 科技成长代表 | 通常比 SPY 波动更大，更早反映风险偏好 |
| Gold ETF | `US.GLD` | 避险情绪代理 | GLD 走强通常意味 risk-off |
| VIX 恐慌指数 | `US.VIX` | 波动率/恐慌度 | 市场的"恐惧温度计" |

### 2.2 Futu API 数据获取

```bash
# 日K线数据（计算技术指标需要约260个交易日 ≈ 1年）
python scripts/quote/get_kline.py US.SPY --ktype 1d --num 260 --json
python scripts/quote/get_kline.py US.QQQ --ktype 1d --num 260 --json
python scripts/quote/get_kline.py US.GLD --ktype 1d --num 260 --json
python scripts/quote/get_kline.py US.VIX --ktype 1d --num 260 --json

# 周K线数据（周线技术面维度，约60根周K ≈ 1.2年）
python scripts/quote/get_kline.py US.SPY --ktype 1w --num 60 --json
python scripts/quote/get_kline.py US.QQQ --ktype 1w --num 60 --json

# 快照数据（最新价、52周高低等）
python scripts/quote/get_snapshot.py US.SPY US.QQQ US.GLD US.VIX --json
```

> **注意**：日 K 线返回字段中 `volume` 用于量能确认维度计算，`close` 用于所有技术指标计算。

快照关键返回字段：

| 字段 | 说明 |
|------|------|
| `last_price` | 最新价 |
| `high_price` / `low_price` | 当日最高/最低 |
| `prev_close_price` | 前收盘价 |
| `high52w` / `low52w` | 52 周最高/最低 |

### 2.3 外部参考（不纳入公式计算）

| 指标 | 链接 | 用途 |
|------|------|------|
| CNN Fear & Greed Index | https://edition.cnn.com/markets/fear-and-greed | 综合情绪参考，观察极端区间 |
| AAII Sentiment Survey | https://www.aaii.com/sentimentsurvey | 散户情绪多空比 |

---

## 3. 综合评分体系

### 3.0 评分方向定义

**综合评分范围 0 ~ 100：**

| 评分区间 | 含义 | 操作方向 |
|---------|------|---------|
| 0 ~ 20 | 极度恐慌 / 超卖 | 应大幅加仓 |
| 20 ~ 40 | 偏悲观 | 逐步加仓 |
| 40 ~ 60 | 中性 | 维持现仓 |
| 60 ~ 80 | 偏贪婪 | 逐步减仓 |
| 80 ~ 100 | 极度贪婪 / 超买 | 大幅减仓 |

### 3.1 六大评分维度与权重

```
综合评分 = 日线技术面(30%) + 周线技术面(15%) + 波动率(25%) + 价格位置(15%) + 量能确认(8%) + 避险信号(7%)
```

| 维度 | 权重 | 输入标的 | 核心逻辑 |
|------|------|---------|---------|
| 日线技术面 | 30% | SPY + QQQ | 日线 RSI/MACD/BOLL 判断超买超卖 |
| 周线技术面 | 15% | SPY + QQQ | 周线 RSI/MACD 过滤日线噪音，确认大级别方向 |
| 波动率 | 25% | VIX | 恐慌度量（反向映射） |
| 价格位置 | 15% | SPY + QQQ | 距高点远近 + MA200偏离度 |
| 量能确认 | 8% | SPY + QQQ | 成交量异常检测（恐慌放量/地量） |
| 避险信号 | 7% | GLD | 避险资产热度（反向映射） |

> **权重设计理由**：
> - 日线技术面（30%）：最直接的超买超卖信号，但从 40% 降至 30%，分出 15% 给周线
> - 周线技术面（15%）：过滤日线噪音，日线 RSI 可能反复超卖但周线还没到位（如 2022 持续阴跌），是判断"跌够没有"的关键
> - 波动率（25%）：VIX 是恐慌实时温度计，从 30% 微降至 25%
> - 价格位置（15%）：从 20% 降至 15%，新增 MA200 偏离度子指标，提供均值回归视角
> - 量能确认（8%）：新增维度——恐慌性放量通常是底部特征，持续缩量阴跌说明还没到底
> - 避险信号（7%）：GLD 受多因素影响，从 10% 降至 7%，作为辅助验证

---

## 4. 各维度评分规则

### 4.1 日线技术面维度（权重 30%）

对 **SPY** 和 **QQQ** 分别计算以下三个子指标，共 6 个评分，取算术平均。

#### 4.1.1 RSI(14) 评分

**参数**：周期 = 14 日

**映射公式**：

```
RSI_score = clamp((RSI - 20) / 60 × 100,  0,  100)
```

| RSI 值 | 评分 | 市场状态 |
|--------|------|---------|
| ≤ 20 | 0 | 极度超卖，恐慌性抛售 |
| 30 | 17 | 超卖区 |
| 40 | 33 | 偏冷 |
| 50 | 50 | 中性 |
| 60 | 67 | 偏热 |
| 70 | 83 | 超买区 |
| ≥ 80 | 100 | 极度超买，FOMO 阶段 |

> **为什么选 [20, 80] 而非 [30, 70]？** 宽指 ETF（SPY/QQQ）的 RSI 极端值比个股更难达到，30/70 已经是比较强的信号，20/80 是极端信号。使用更宽的区间让中间段评分更有区分度。

#### 4.1.2 MACD(12,26,9) 柱状图评分

**参数**：快线 = 12，慢线 = 26，信号线 = 9

**评分方法**：使用 MACD 柱状图（histogram = DIF - DEA）在**过去 252 个交易日**中的百分位排名。

```
MACD_score = percentile_rank(current_histogram, lookback=252) × 100
```

| MACD 柱状图分位数 | 评分 | 含义 |
|------------------|------|------|
| 0th ~ 10th | 0 ~ 10 | 柱状图深度负值，下跌动能极强 |
| 10th ~ 30th | 10 ~ 30 | 偏弱 |
| 30th ~ 70th | 30 ~ 70 | 中性 |
| 70th ~ 90th | 70 ~ 90 | 偏强 |
| 90th ~ 100th | 90 ~ 100 | 柱状图极端正值，上涨动能可能过热 |

> **为什么用百分位而非绝对值？** MACD histogram 的绝对值取决于股价水平，SPY 500 和 QQQ 400 的 histogram 尺度完全不同，百分位数天然归一化。

#### 4.1.3 布林带 %B(20, 2) 评分

**参数**：周期 = 20 日，标准差倍数 = 2

**%B 定义**：

```
%B = (Price - Lower_Band) / (Upper_Band - Lower_Band)
```

**映射公式**：

```
BB_score = clamp(%B × 100,  0,  100)
```

| %B 值 | 评分 | 含义 |
|-------|------|------|
| ≤ 0 | 0 | 价格跌破下轨，极度超卖 |
| 0.2 | 20 | 接近下轨 |
| 0.5 | 50 | 中轨附近 |
| 0.8 | 80 | 接近上轨 |
| ≥ 1.0 | 100 | 价格突破上轨，极度超买 |

#### 4.1.4 日线技术面综合评分

```
daily_tech_score = (SPY_RSI + QQQ_RSI + SPY_MACD + QQQ_MACD + SPY_BB + QQQ_BB) / 6
```

---

### 4.2 周线技术面维度（权重 15%）

对 **SPY** 和 **QQQ** 的**周线 K 线**分别计算 RSI 和 MACD，共 4 个评分，取算术平均。

> **数据需求**：需要约 60 根周 K 线（≈ 1.2 年），Futu API 获取方式：
> ```bash
> python scripts/quote/get_kline.py US.SPY --ktype 1w --num 60 --json
> python scripts/quote/get_kline.py US.QQQ --ktype 1w --num 60 --json
> ```

#### 4.2.1 周线 RSI(14) 评分

**映射公式**（与日线相同）：

```
Weekly_RSI_score = clamp((Weekly_RSI - 20) / 60 × 100,  0,  100)
```

| 周线 RSI 值 | 评分 | 市场状态 |
|------------|------|---------|
| ≤ 20 | 0 | 极度超卖（2008/2020级别，非常罕见） |
| 30 | 17 | 周级别超卖，大级别底部信号 |
| 40 | 33 | 偏弱 |
| 50 | 50 | 中性 |
| 60 | 67 | 偏强 |
| 70 | 83 | 周级别超买 |
| ≥ 80 | 100 | 极度超买（牛市末期） |

> **周线 RSI vs 日线 RSI 的区别**：宽指 ETF 周线 RSI 极少低于 30（只在 2008、2011、2020、2022 出现过），一旦到 30 以下基本是大级别底部区域。日线 RSI 到 30 则较常见，可能只是正常回调。

#### 4.2.2 周线 MACD(12,26,9) 柱状图评分

**评分方法**：与日线相同，使用百分位排名，但回溯窗口为 **52 根周 K**（约 1 年）。

```
Weekly_MACD_score = percentile_rank(weekly_histogram, lookback=52) × 100
```

#### 4.2.3 周线技术面综合评分

```
weekly_tech_score = (SPY_Weekly_RSI + QQQ_Weekly_RSI + SPY_Weekly_MACD + QQQ_Weekly_MACD) / 4
```

> **为什么周线不加布林带？** 周线布林带需要 20 根周 K 才开始稳定，数据点较少时噪音大。RSI + MACD 已足够判断周级别的超买超卖和动能方向。

---

### 4.3 波动率维度（权重 25%）

VIX 与恐慌正相关——**反向映射**：VIX 越高 → 评分越低 → 应加仓。

#### 4.3.1 VIX 绝对值评分

**映射公式**：

```
VIX_abs_score = clamp((40 - VIX) / 28 × 100,  0,  100)
```

| VIX 值 | 评分 | 市场状态 |
|--------|------|---------|
| ≥ 40 | 0 | 极度恐慌（2020.03 / 2008.10 级别） |
| 35 | 18 | 高度恐慌 |
| 30 | 36 | 恐慌 |
| 25 | 54 | 偏紧张 |
| 20 | 71 | 正常偏平静 |
| 15 | 89 | 低波动，偏自满 |
| ≤ 12 | 100 | 极度自满（风险积聚信号） |

> **关键阈值参考**：
> - VIX 12-15：市场极度平静，往往是暴风雨前的宁静
> - VIX 20-25：正常波动区间
> - VIX 30+：市场已进入恐慌，历史上是不错的买点区间
> - VIX 40+：极端恐慌，如 2020 年 3 月、2008 年金融危机

#### 4.3.2 VIX 历史分位数评分

**映射公式**：

```
VIX_pct_score = (1 - percentile_rank(VIX, lookback=252)) × 100
```

| VIX 分位数 | 评分 | 含义 |
|-----------|------|------|
| 95th+ | 0 ~ 5 | VIX 处于一年内最高水平，极度恐慌 |
| 75th | 25 | 偏高 |
| 50th | 50 | 中位数 |
| 25th | 75 | 偏低 |
| 5th 以下 | 95 ~ 100 | VIX 处于一年内最低水平，极度自满 |

#### 4.3.3 波动率综合评分

```
vol_score = VIX_abs_score × 0.5 + VIX_pct_score × 0.5
```

> **为什么各占 50%？** 绝对值评分捕捉"是否到了极端恐慌/自满的绝对水平"，分位数评分捕捉"相对于近一年 VIX 是高还是低"。两者互补——长期低波动环境下（如 2017 年），VIX = 15 的绝对值评分是 89（偏高），但分位数可能只有 50（中性），平衡后更合理。

---

### 4.4 价格位置维度（权重 15%）

对 **SPY** 和 **QQQ** 分别计算三个子指标，共 6 个评分，取算术平均。

#### 4.4.1 52 周相对位置评分

**映射公式**：

```
pos_52w = (Price - Low_52w) / (High_52w - Low_52w)
score_52w = clamp(pos_52w × 100,  0,  100)
```

| 52 周位置 | 评分 | 含义 |
|----------|------|------|
| 接近 52 周低点 | 0 ~ 20 | 深度回调区 |
| 中间位置 | 40 ~ 60 | 正常波动 |
| 接近 52 周高点 | 80 ~ 100 | 高位区间 |

#### 4.4.2 距历史最高点（ATH）回撤评分

**映射公式**：

```
drawdown = (ATH - Price) / ATH           # 0 表示在ATH，0.2 表示回撤 20%
ATH_score = clamp((1 - drawdown / 0.20) × 100,  0,  100)
```

| 距 ATH 回撤幅度 | 评分 | 含义 |
|----------------|------|------|
| 0%（创新高） | 100 | 价格在历史最高，可能过热 |
| -5% | 75 | 小幅回调 |
| -10% | 50 | 技术性回调 |
| -15% | 25 | 较深回调 |
| ≥ -20% | 0 | 进入技术性熊市区间 |

> **ATH 数据获取**：Futu 快照不直接提供 ATH，可通过拉取较长历史 K 线（如 5 年日 K）取最高收盘价计算：
> ```bash
> python scripts/quote/get_kline.py US.SPY --ktype 1d --start 2021-01-01 --end 2026-04-30 --json
> ```

#### 4.4.3 MA200 偏离度评分

**定义**：当前价格相对 200 日均线的偏离程度。

```
MA200_dev = (Price - MA200) / MA200
MA200_score = clamp((MA200_dev + 0.20) / 0.40 × 100,  0,  100)
```

| MA200 偏离度 | 评分 | 含义 |
|-------------|------|------|
| ≤ -20% | 0 | 极度偏离均线下方（恐慌性超跌，均值回归动能强） |
| -10% | 25 | 显著低于均线 |
| 0%（在MA200上） | 50 | 中性 |
| +10% | 75 | 显著高于均线 |
| ≥ +20% | 100 | 极度偏离均线上方（过热，回归压力大） |

> **为什么加 MA200 偏离度？** 52 周位置和 ATH 回撤只告诉你"从高点跌了多少"，但不能区分"均线本身也在下行（趋势破坏）"vs"价格急跌远离均线（超跌反弹概率高）"。偏离度捕捉的是均值回归的弹性空间。

#### 4.4.4 价格位置综合评分

```
price_score = (SPY_52w + QQQ_52w + SPY_ATH + QQQ_ATH + SPY_MA200 + QQQ_MA200) / 6
```

---

### 4.5 量能确认维度（权重 8%）

成交量是判断底部的重要辅助信号。恐慌性放量通常标志情绪宣泄完毕（卖盘枯竭），而持续缩量阴跌说明卖压尚未释放。

对 **SPY** 和 **QQQ** 分别计算两个子指标，共 4 个评分，取算术平均。

#### 4.5.1 量比评分

**定义**：当日成交量与 20 日平均成交量的比值。

```
vol_ratio = today_volume / MA20_volume
```

**评分方法（非线性映射）**：

| 量比 | 评分 | 含义 |
|------|------|------|
| ≥ 3.0 | 0 | 恐慌性放量（恐慌高潮，可能是底部） |
| 2.0 | 20 | 显著放量（情绪亢奋/恐慌） |
| 1.5 | 40 | 温和放量 |
| 1.0 | 55 | 正常量能 |
| 0.7 | 70 | 缩量（关注方向） |
| ≤ 0.5 | 30 | 地量（底部区域信号，但方向不明确） |

```
# 量比评分需结合价格方向：
if price_change < 0:  # 下跌日
    if vol_ratio >= 2.5:
        vol_ratio_score = 0    # 恐慌放量抛售 → 情绪极度恐慌
    elif vol_ratio >= 1.5:
        vol_ratio_score = 25   # 放量下跌 → 偏恐慌
    elif vol_ratio <= 0.5:
        vol_ratio_score = 35   # 地量阴跌 → 卖盘枯竭，接近底部
    else:
        vol_ratio_score = 45   # 正常缩量下跌
else:  # 上涨日
    if vol_ratio >= 2.0:
        vol_ratio_score = 80   # 放量上涨 → 买盘强势
    elif vol_ratio >= 1.2:
        vol_ratio_score = 65   # 温和放量上涨
    elif vol_ratio <= 0.5:
        vol_ratio_score = 40   # 缩量上涨 → 假反弹
    else:
        vol_ratio_score = 55   # 正常
```

#### 4.5.2 5 日量能趋势评分

**定义**：近 5 日平均成交量与 20 日平均成交量的比值，判断量能趋势。

```
vol_trend = MA5_volume / MA20_volume
```

**评分规则**（结合近 5 日价格方向）：

```
avg_return_5d = (close - close_5d_ago) / close_5d_ago

if avg_return_5d < -0.03:  # 近5日下跌超3%
    # 下跌趋势中
    if vol_trend >= 2.0:
        vol_trend_score = 5    # 持续放量暴跌，恐慌未结束
    elif vol_trend >= 1.3:
        vol_trend_score = 20   # 放量下跌
    elif vol_trend <= 0.6:
        vol_trend_score = 40   # 缩量下跌，卖压减弱
    else:
        vol_trend_score = 30
elif avg_return_5d > 0.03:  # 近5日上涨超3%
    # 反弹趋势中
    if vol_trend >= 1.5:
        vol_trend_score = 85   # 放量反弹，买盘入场
    else:
        vol_trend_score = 60   # 缩量反弹，持续性存疑
else:
    vol_trend_score = 50  # 横盘震荡，中性
```

#### 4.5.3 量能确认综合评分

```
volume_score = (SPY_vol_ratio + QQQ_vol_ratio + SPY_vol_trend + QQQ_vol_trend) / 4
```

> **量能维度的特殊性**：与其他维度不同，量能本身不是线性的"越低越好买"。恐慌放量（评分极低）实际上是**底部确认信号**——结合综合评分已经很低时，放量恐慌反而加强了"该加仓"的判断。这也是权重只给 8% 的原因，它更多是验证性质。

---

### 4.6 避险信号维度（权重 7%）

GLD 上涨通常反映避险需求上升，与权益市场恐慌正相关。因此 GLD 的技术指标采用**反向映射**：GLD 越强（RSI高/MACD强/突破上轨）→ 评分越低 → 意味着权益市场偏冷 → 应加仓权益。

#### 4.6.1 GLD RSI(14) 反向评分

```
GLD_RSI_score = clamp((80 - GLD_RSI) / 60 × 100,  0,  100)
```

| GLD RSI | 评分 | 含义 |
|---------|------|------|
| ≥ 80 | 0 | 黄金极度超买，避险需求爆表 → 权益极恐慌 |
| 60 | 33 | 黄金偏强 → 权益偏冷 |
| 50 | 50 | 中性 |
| 30 | 83 | 黄金偏弱 → 权益偏乐观 |
| ≤ 20 | 100 | 黄金极度超卖 → 权益极贪婪 |

#### 4.6.2 GLD MACD 柱状图反向评分

```
GLD_MACD_score = (1 - percentile_rank(GLD_histogram, lookback=252)) × 100
```

#### 4.6.3 GLD 布林带 %B 反向评分

```
GLD_BB_score = clamp((1 - GLD_%B) × 100,  0,  100)
```

#### 4.6.4 避险信号综合评分

```
safe_haven_score = (GLD_RSI_score + GLD_MACD_score + GLD_BB_score) / 3
```

> **局限性说明**：GLD 受黄金供需、美元指数、实际利率、央行购金等多因素影响，并非纯粹的避险指标。权重设为 10% 正是为了限制其影响，仅作为情绪验证的辅助信号。当 GLD 走势与 SPY/QQQ 出现异常同向时，参见第 7 节特殊情况处理。

---

## 5. 综合评分与仓位映射

### 5.1 综合评分公式

```
composite = daily_tech_score   × 0.30
           + weekly_tech_score × 0.15
           + vol_score         × 0.25
           + price_score       × 0.15
           + volume_score      × 0.08
           + safe_haven_score  × 0.07
```

### 5.2 仓位映射公式

**常规区间（评分 > 15）：**

```
target_position(%) = 90 - composite × 0.8
```

**极端区间（评分 ≤ 15，需满足额外触发条件）：**

```
若满足极端触发条件：
  target_position(%) = 90 + (15 - composite) × 2
  钳位到 [90%, 120%]

若不满足极端触发条件：
  维持常规公式，上限 90%
```

| 综合评分 | 市场状态 | 目标仓位 | 操作建议 |
|---------|---------|---------|---------|
| 0 ~ 5 | 极端恐慌 + 触发 | 110% ~ 120% | 融资满仓 + 期权超配 |
| 5 ~ 10 | 极端恐慌 + 触发 | 100% ~ 110% | 融资加仓 |
| 10 ~ 15 | 极度恐慌 + 触发 | 90% ~ 100% | 融资补满 |
| 0 ~ 15 | 极度恐慌（未触发） | 78% ~ 90% | 重仓逆势买入，分批抄底 |
| 15 ~ 30 | 偏悲观 | 66% ~ 78% | 积极加仓，越跌越买 |
| 30 ~ 45 | 略偏冷 | 54% ~ 66% | 适度加仓 |
| 45 ~ 55 | 中性 | 46% ~ 54% | 维持当前仓位 |
| 55 ~ 70 | 略偏热 | 34% ~ 46% | 适度减仓 |
| 70 ~ 85 | 偏贪婪 | 22% ~ 34% | 积极减仓 |
| 85 ~ 100 | 极度贪婪 | 10% ~ 22% | 大幅减仓，只留鱼尾仓 |

### 5.3 极端层触发条件

进入杠杆区（仓位 > 90%）需**同时满足**以下条件：

| # | 条件 | 理由 |
|---|------|------|
| 1 | 综合评分 ≤ 15 | 系统已确认极度恐慌 |
| 2 | SPY **周线** RSI(14) < 30 | 周级别超卖确认，非日内噪音 |
| 3 | SPY **日线** RSI(14) < 25 | 日级别深度超卖 |
| 4 | VIX > 35 | 恐慌充分释放 |

**极端层内部分级：**

| 仓位目标 | 额外条件 | 执行工具 |
|---------|---------|---------|
| 90% ~ 100% | 满足上述 4 条 | **融资买入**现货 ETF（SPY/QQQ） |
| 100% ~ 110% | + 日线 RSI < 15 | 融资 + 轻度 OTM Call（Delta 0.3~0.4） |
| 110% ~ 120% | + 周线 RSI < 15（个位数级别） | 融资满额 + 加大期权仓位 |

### 5.4 底部确认辅助信号（不参与公式计算，人工参考）

以下信号不纳入评分公式，但在极端层触发后可作为**择时加仓的辅助确认**：

| 信号 | 定义 | 确认含义 |
|------|------|---------|
| RSI 底背离 | 价格创新低，但日线 RSI(14) 未创新低 | 下跌动能衰竭，底部概率高 |
| MACD 零轴下金叉 | DIF 在零轴以下上穿 DEA | 短期反转动能启动 |
| 布林带收口 | 布林带宽度（bandwidth）从极端扩张开始收窄 | 波动率从恐慌回归正常 |
| 恐慌放量后缩量 | 某日量比>2.5 暴跌后，后续 2~3 日量比回落至<1.0 | 卖盘枯竭，恐慌情绪释放完毕 |

> **使用方法**：极端层已触发，若同时出现 2 个以上确认信号，可更积极执行融资/期权加仓；若无确认信号，则按分批节奏逐步执行。

---

### 5.5 杠杆区执行规则

| 规则 | 说明 |
|------|------|
| 融资比例上限 | 账户净值的 **30%**（即最大融资后总仓位 = 净值 × 1.3） |
| 期权资金上限 | 账户净值的 **10%**（权利金口径） |
| 期权选择 | 到期日 30~60 天，行权价 OTM 3~5%（Delta 0.3~0.4） |
| 期权止损 | 权利金亏损 50% 无条件平仓 |
| 融资持有期限 | 指标回到中性区（评分 > 45）后 **5 个交易日内** 偿还融资 |
| 强制退出 | 评分回升至 30 以上 → 期权获利了结；评分回升至 45 以上 → 融资全部偿还 |

> **风控底线**：融资 + 期权的最大潜在亏损不得超过账户净值的 **20%**。即极端情况下（融资爆仓+期权归零），总亏损可控。

### 5.6 仓位映射可视化

```
仓位
120%|■                          ← 融资+期权（极端恐慌，周线RSI个位数）
    |■■
110%|■■■                        ← 融资+轻度期权
    |■■■■
100%|■■■■■                      ← 融资满仓
    |■■■■■■
 90%|■■■■■■■ ─ ─ ─ ─ ─ ─ ─ ─  ← 杠杆线（以上需满足极端触发条件）
    |■■■■■■■■
 80%|■■■■■■■■■
    |■■■■■■■■■■
 70%|■■■■■■■■■■■
    |■■■■■■■■■■■■
 60%|■■■■■■■■■■■■■
    |■■■■■■■■■■■■■■
 50%|■■■■■■■■■■■■■■■            ← 中性线
    |■■■■■■■■■■■■■■■■
 40%|■■■■■■■■■■■■■■■■■
    |■■■■■■■■■■■■■■■■■■
 30%|■■■■■■■■■■■■■■■■■■■
    |■■■■■■■■■■■■■■■■■■■■
 20%|■■■■■■■■■■■■■■■■■■■■■
    |■■■■■■■■■■■■■■■■■■■■■■
 10%|■■■■■■■■■■■■■■■■■■■■■■■
    +----+----+----+----+----→ 综合评分
    0   20   40   60   80  100
   恐慌              →           贪婪
```

---

## 6. 调仓规则

### 6.1 评估节奏

| 场景 | 频率 | 说明 |
|------|------|------|
| 常规评估 | 每周一次 | 周日晚/周一盘前运行脚本 |
| 临时评估 | 事件触发 | 见下方触发条件 |

**临时评估触发条件**（满足任一即触发）：
- SPY 或 QQQ 单日跌幅 > 3%
- VIX 日内升幅 > 30%（如从 20 升至 26+）
- VIX 突破 35（恐慌级别）
- VIX 跌破 12（自满级别）

### 6.2 单次调仓幅度限制

| 规则 | 限制 |
|------|------|
| 单次最大调仓 | 总仓位的 **15%** |
| 大幅偏离处理 | 目标仓位与当前仓位差 > 30% 时，分 2~3 次调整 |
| 分批间隔 | 每批间隔 **2~3 个交易日** |

**示例**：当前仓位 40%，评分骤降至 10（目标仓位 82%），差距 42%：
- 第 1 次：40% → 55%（+15%）
- 间隔 2 日
- 第 2 次：55% → 70%（+15%）
- 间隔 2 日
- 第 3 次：70% → 82%（+12%）

### 6.3 冷却期

| 规则 | 说明 |
|------|------|
| 常规冷却 | 调仓后至少 **3 个交易日** 不再调仓 |
| 冷却期例外 | VIX 突破 35 或跌破 12 时可无视冷却期 |

### 6.4 仓位硬限制

| 限制 | 值 | 理由 |
|------|------|------|
| 最低仓位 | **10%** | 保留底仓防踏空 |
| 常规最高仓位 | **90%** | 保留现金作安全垫和加仓弹药 |
| 杠杆区最高仓位 | **120%** | 需满足极端触发条件（见 5.3 节） |
| 融资上限 | 净值 **30%** | 控制爆仓风险 |
| 期权上限 | 净值 **10%**（权利金） | 亏损封顶 |

---

## 7. 特殊情况处理

### 7.1 数据缺失

某个指标数据获取失败时，该指标评分设为 **50（中性）**，权重不变。

```
例：VIX 数据获取失败
→ VIX_abs_score = 50, VIX_pct_score = 50
→ vol_score = 50
→ 其余维度正常计算
```

### 7.2 极端行情加速规则

| 触发条件 | 特殊规则 |
|---------|---------|
| SPY 或 QQQ 单日暴跌 > 5% | 忽略冷却期 + 单次调仓上限放宽至 **25%** |
| 综合评分 < 10 持续 3 天以上 | 可一次性调仓至目标仓位（忽略分批限制） |

### 7.3 GLD 与 SPY/QQQ 同向异常

| 场景 | 处理 |
|------|------|
| GLD 与 SPY/QQQ 同时大涨 | 可能是流动性驱动（非典型避险），避险权重减半至 **5%**，技术面增至 **45%** |
| GLD 与 SPY/QQQ 同时大跌 | 可能是流动性危机，综合评分 **×0.8**（偏向加仓） |

**"同时大涨/大跌"定义**：GLD 与 SPY 的 5 日涨跌幅同号且绝对值均 > 3%。

### 7.4 市场结构性变化

当出现以下情况时，建议人工介入判断，暂停纯公式操作：
- 美联储紧急会议或突发政策（如紧急降息/加息）
- 重大地缘政治事件（战争爆发等）
- 市场熔断

---

## 8. 指标计算代码参考

### 8.1 RSI 计算

```python
import pandas as pd

def calc_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """计算 RSI(14)"""
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))
```

### 8.2 MACD 计算

```python
def calc_macd(closes: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """计算 MACD，返回 (DIF, DEA, Histogram)"""
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    histogram = dif - dea
    return dif, dea, histogram
```

### 8.3 布林带 %B 计算

```python
def calc_bollinger_pctb(closes: pd.Series, period: int = 20, std_dev: int = 2) -> pd.Series:
    """计算 Bollinger %B"""
    sma = closes.rolling(window=period).mean()
    std = closes.rolling(window=period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    pct_b = (closes - lower) / (upper - lower)
    return pct_b
```

### 8.4 百分位排名

```python
def percentile_rank(series: pd.Series, current_value: float, lookback: int = 252) -> float:
    """计算当前值在过去 lookback 天中的百分位排名 (0~1)"""
    window = series.tail(lookback)
    return (window < current_value).sum() / len(window)
```

### 8.5 MA200 偏离度计算

```python
def calc_ma200_deviation(closes: pd.Series) -> float:
    """计算当前价格相对 MA200 的偏离度"""
    ma200 = closes.rolling(window=200).mean().iloc[-1]
    current_price = closes.iloc[-1]
    return (current_price - ma200) / ma200

def score_ma200_deviation(deviation: float) -> float:
    """MA200偏离度映射到评分 (偏离 -20%→0分, 0%→50分, +20%→100分)"""
    return clamp((deviation + 0.20) / 0.40 * 100)
```

### 8.6 量能评分计算

```python
def calc_volume_score(closes: pd.Series, volumes: pd.Series) -> dict:
    """
    计算量能评分
    - closes: 日收盘价序列
    - volumes: 日成交量序列
    """
    today_volume = volumes.iloc[-1]
    ma20_volume = volumes.rolling(20).mean().iloc[-1]
    ma5_volume = volumes.tail(5).mean()
    vol_ratio = today_volume / ma20_volume
    vol_trend = ma5_volume / ma20_volume

    price_change = (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2]
    avg_return_5d = (closes.iloc[-1] - closes.iloc[-6]) / closes.iloc[-6]

    # 量比评分（结合当日涨跌方向）
    if price_change < 0:
        if vol_ratio >= 2.5:
            vol_ratio_score = 0
        elif vol_ratio >= 1.5:
            vol_ratio_score = 25
        elif vol_ratio <= 0.5:
            vol_ratio_score = 35
        else:
            vol_ratio_score = 45
    else:
        if vol_ratio >= 2.0:
            vol_ratio_score = 80
        elif vol_ratio >= 1.2:
            vol_ratio_score = 65
        elif vol_ratio <= 0.5:
            vol_ratio_score = 40
        else:
            vol_ratio_score = 55

    # 5日量能趋势评分
    if avg_return_5d < -0.03:
        if vol_trend >= 2.0:
            vol_trend_score = 5
        elif vol_trend >= 1.3:
            vol_trend_score = 20
        elif vol_trend <= 0.6:
            vol_trend_score = 40
        else:
            vol_trend_score = 30
    elif avg_return_5d > 0.03:
        if vol_trend >= 1.5:
            vol_trend_score = 85
        else:
            vol_trend_score = 60
    else:
        vol_trend_score = 50

    return {
        'vol_ratio': round(vol_ratio, 2),
        'vol_trend': round(vol_trend, 2),
        'vol_ratio_score': vol_ratio_score,
        'vol_trend_score': vol_trend_score,
    }
```

### 8.7 综合评分计算

```python
import numpy as np

def clamp(value, lo=0, hi=100):
    return max(lo, min(hi, value))

def calc_composite_score(spy_closes, qqq_closes, gld_closes, vix_closes,
                         spy_volumes, qqq_volumes,
                         spy_weekly_closes, qqq_weekly_closes,
                         spy_price, qqq_price,
                         spy_52w_high, spy_52w_low, qqq_52w_high, qqq_52w_low,
                         spy_ath, qqq_ath, vix_current):
    """
    计算综合评分（六维度版本）
    - *_closes: pd.Series，至少 260 个交易日的收盘价
    - *_volumes: pd.Series，至少 20 个交易日的成交量
    - *_weekly_closes: pd.Series，至少 60 根周K收盘价
    - *_price: 当前价格
    - *_52w_*: 52周高低
    - *_ath: 历史最高价
    - vix_current: VIX 当前值
    """

    # === 日线技术面 (30%) ===
    spy_rsi = calc_rsi(spy_closes).iloc[-1]
    qqq_rsi = calc_rsi(qqq_closes).iloc[-1]
    spy_rsi_score = clamp((spy_rsi - 20) / 60 * 100)
    qqq_rsi_score = clamp((qqq_rsi - 20) / 60 * 100)

    _, _, spy_hist = calc_macd(spy_closes)
    _, _, qqq_hist = calc_macd(qqq_closes)
    spy_macd_score = percentile_rank(spy_hist, spy_hist.iloc[-1], 252) * 100
    qqq_macd_score = percentile_rank(qqq_hist, qqq_hist.iloc[-1], 252) * 100

    spy_bb = calc_bollinger_pctb(spy_closes).iloc[-1]
    qqq_bb = calc_bollinger_pctb(qqq_closes).iloc[-1]
    spy_bb_score = clamp(spy_bb * 100)
    qqq_bb_score = clamp(qqq_bb * 100)

    daily_tech_score = (spy_rsi_score + qqq_rsi_score + spy_macd_score +
                        qqq_macd_score + spy_bb_score + qqq_bb_score) / 6

    # === 周线技术面 (15%) ===
    spy_weekly_rsi = calc_rsi(spy_weekly_closes).iloc[-1]
    qqq_weekly_rsi = calc_rsi(qqq_weekly_closes).iloc[-1]
    spy_weekly_rsi_score = clamp((spy_weekly_rsi - 20) / 60 * 100)
    qqq_weekly_rsi_score = clamp((qqq_weekly_rsi - 20) / 60 * 100)

    _, _, spy_weekly_hist = calc_macd(spy_weekly_closes)
    _, _, qqq_weekly_hist = calc_macd(qqq_weekly_closes)
    spy_weekly_macd_score = percentile_rank(spy_weekly_hist, spy_weekly_hist.iloc[-1], 52) * 100
    qqq_weekly_macd_score = percentile_rank(qqq_weekly_hist, qqq_weekly_hist.iloc[-1], 52) * 100

    weekly_tech_score = (spy_weekly_rsi_score + qqq_weekly_rsi_score +
                         spy_weekly_macd_score + qqq_weekly_macd_score) / 4

    # === 波动率 (25%) ===
    vix_abs_score = clamp((40 - vix_current) / 28 * 100)
    vix_pct_score = (1 - percentile_rank(vix_closes, vix_current, 252)) * 100
    vol_score = vix_abs_score * 0.5 + vix_pct_score * 0.5

    # === 价格位置 (15%) ===
    spy_52w_score = clamp((spy_price - spy_52w_low) / (spy_52w_high - spy_52w_low) * 100)
    qqq_52w_score = clamp((qqq_price - qqq_52w_low) / (qqq_52w_high - qqq_52w_low) * 100)
    spy_dd = (spy_ath - spy_price) / spy_ath
    qqq_dd = (qqq_ath - qqq_price) / qqq_ath
    spy_ath_score = clamp((1 - spy_dd / 0.20) * 100)
    qqq_ath_score = clamp((1 - qqq_dd / 0.20) * 100)
    spy_ma200_dev = calc_ma200_deviation(spy_closes)
    qqq_ma200_dev = calc_ma200_deviation(qqq_closes)
    spy_ma200_score = score_ma200_deviation(spy_ma200_dev)
    qqq_ma200_score = score_ma200_deviation(qqq_ma200_dev)
    price_score = (spy_52w_score + qqq_52w_score + spy_ath_score +
                   qqq_ath_score + spy_ma200_score + qqq_ma200_score) / 6

    # === 量能确认 (8%) ===
    spy_vol = calc_volume_score(spy_closes, spy_volumes)
    qqq_vol = calc_volume_score(qqq_closes, qqq_volumes)
    volume_score = (spy_vol['vol_ratio_score'] + qqq_vol['vol_ratio_score'] +
                    spy_vol['vol_trend_score'] + qqq_vol['vol_trend_score']) / 4

    # === 避险信号 (7%) ===
    gld_rsi = calc_rsi(gld_closes).iloc[-1]
    _, _, gld_hist = calc_macd(gld_closes)
    gld_bb = calc_bollinger_pctb(gld_closes).iloc[-1]
    gld_rsi_score = clamp((80 - gld_rsi) / 60 * 100)
    gld_macd_score = (1 - percentile_rank(gld_hist, gld_hist.iloc[-1], 252)) * 100
    gld_bb_score = clamp((1 - gld_bb) * 100)
    safe_haven_score = (gld_rsi_score + gld_macd_score + gld_bb_score) / 3

    # === 综合 ===
    composite = (daily_tech_score * 0.30 + weekly_tech_score * 0.15 +
                 vol_score * 0.25 + price_score * 0.15 +
                 volume_score * 0.08 + safe_haven_score * 0.07)

    # === 极端层判断 ===
    extreme_triggered = (
        composite <= 15
        and spy_rsi < 25
        and spy_weekly_rsi < 30
        and vix_current > 35
    )

    if extreme_triggered:
        # 极端公式：90 + (15 - composite) × 2，钳位 [90, 120]
        target_position = clamp(90 + (15 - composite) * 2, 90, 120)
    else:
        target_position = clamp(90 - composite * 0.8, 10, 90)

    # === 杠杆工具建议 ===
    leverage_tool = 'none'
    if target_position > 100:
        leverage_tool = 'margin + OTM_call'
    elif target_position > 90:
        leverage_tool = 'margin'

    return {
        'daily_tech_score': round(daily_tech_score, 1),
        'weekly_tech_score': round(weekly_tech_score, 1),
        'vol_score': round(vol_score, 1),
        'price_score': round(price_score, 1),
        'volume_score': round(volume_score, 1),
        'safe_haven_score': round(safe_haven_score, 1),
        'composite_score': round(composite, 1),
        'target_position_pct': round(target_position, 1),
        'extreme_triggered': extreme_triggered,
        'leverage_tool': leverage_tool,
        # 子指标明细
        'detail': {
            # 日线技术面
            'SPY_RSI': round(spy_rsi, 1), 'SPY_RSI_score': round(spy_rsi_score, 1),
            'QQQ_RSI': round(qqq_rsi, 1), 'QQQ_RSI_score': round(qqq_rsi_score, 1),
            'SPY_MACD_score': round(spy_macd_score, 1),
            'QQQ_MACD_score': round(qqq_macd_score, 1),
            'SPY_BB_%B': round(spy_bb, 3), 'SPY_BB_score': round(spy_bb_score, 1),
            'QQQ_BB_%B': round(qqq_bb, 3), 'QQQ_BB_score': round(qqq_bb_score, 1),
            # 周线技术面
            'SPY_Weekly_RSI': round(spy_weekly_rsi, 1), 'SPY_Weekly_RSI_score': round(spy_weekly_rsi_score, 1),
            'QQQ_Weekly_RSI': round(qqq_weekly_rsi, 1), 'QQQ_Weekly_RSI_score': round(qqq_weekly_rsi_score, 1),
            'SPY_Weekly_MACD_score': round(spy_weekly_macd_score, 1),
            'QQQ_Weekly_MACD_score': round(qqq_weekly_macd_score, 1),
            # 波动率
            'VIX': round(vix_current, 2),
            'VIX_abs_score': round(vix_abs_score, 1),
            'VIX_pct_score': round(vix_pct_score, 1),
            # 价格位置
            'SPY_52w_score': round(spy_52w_score, 1),
            'QQQ_52w_score': round(qqq_52w_score, 1),
            'SPY_ATH_score': round(spy_ath_score, 1),
            'QQQ_ATH_score': round(qqq_ath_score, 1),
            'SPY_MA200_dev': round(spy_ma200_dev, 4),
            'SPY_MA200_score': round(spy_ma200_score, 1),
            'QQQ_MA200_dev': round(qqq_ma200_dev, 4),
            'QQQ_MA200_score': round(qqq_ma200_score, 1),
            # 量能
            'SPY_vol_ratio': spy_vol['vol_ratio'],
            'SPY_vol_ratio_score': spy_vol['vol_ratio_score'],
            'SPY_vol_trend': spy_vol['vol_trend'],
            'SPY_vol_trend_score': spy_vol['vol_trend_score'],
            'QQQ_vol_ratio': qqq_vol['vol_ratio'],
            'QQQ_vol_ratio_score': qqq_vol['vol_ratio_score'],
            'QQQ_vol_trend': qqq_vol['vol_trend'],
            'QQQ_vol_trend_score': qqq_vol['vol_trend_score'],
            # 避险
            'GLD_RSI': round(gld_rsi, 1), 'GLD_RSI_score': round(gld_rsi_score, 1),
            'GLD_MACD_score': round(gld_macd_score, 1),
            'GLD_BB_score': round(gld_bb_score, 1),
        }
    }
```

---

## 9. 历史场景回测验证

以下为关键历史时刻的指标近似值和策略建议，用于验证评分逻辑的合理性。

### 9.1 2020年3月 — COVID 崩盘底部

| 指标 | 近似值 | 评分 |
|------|--------|------|
| SPY RSI(14) | ~22 | 3 |
| QQQ RSI(14) | ~25 | 8 |
| SPY MACD hist | ~1st percentile | 1 |
| QQQ MACD hist | ~2nd percentile | 2 |
| SPY BB %B | ~-0.05 | 0 |
| QQQ BB %B | ~0.02 | 2 |
| **技术面** | | **~3** |
| VIX 绝对值 | ~82 | 0 |
| VIX 分位数 | ~99th | 1 |
| **波动率** | | **~1** |
| SPY 52w 位置 | ~10% | 10 |
| QQQ 52w 位置 | ~15% | 15 |
| SPY ATH | -34% | 0 |
| QQQ ATH | -28% | 0 |
| **价格位置** | | **~6** |
| GLD RSI(inv) | RSI~55 → 42 | 42 |
| GLD MACD(inv) | ~35th pct → 65 | 65 |
| GLD BB(inv) | %B~0.6 → 40 | 40 |
| **避险信号** | | **~49** |

**综合评分** = 3×0.4 + 1×0.3 + 6×0.2 + 49×0.1 = 1.2 + 0.3 + 1.2 + 4.9 = **~8**

**极端触发判断**：
- 综合评分 8 ≤ 15 ✅
- SPY 日线 RSI ≈ 22 < 25 ✅
- VIX ≈ 82 > 35 ✅
- SPY 周线 RSI ≈ 18 < 30 ✅
- → **极端层触发！**

**建议仓位** = 90 + (15 - 8) × 2 = **104%** → **融资加仓** ✅

**执行方案**：90% 现货（满仓）+ 14% 融资买入 SPY/QQQ，另可用≤10% 权利金买入 30-60天 OTM 3-5% Call

### 9.2 2021年底 — 市场见顶前

| 指标 | 近似值 | 评分 |
|------|--------|------|
| SPY RSI(14) | ~68 | 80 |
| QQQ RSI(14) | ~72 | 87 |
| MACD hist | ~90th+ | 90 |
| BB %B | ~0.9+ | 92 |
| **技术面** | | **~87** |
| VIX | ~18 | 79 |
| VIX 分位 | ~30th | 70 |
| **波动率** | | **~75** |
| 52w/ATH 位置 | 接近 ATH | ~95 |
| **价格位置** | | **~95** |
| GLD(inv) | GLD 偏弱 | ~70 |
| **避险信号** | | **~70** |

**综合评分** = 87×0.4 + 75×0.3 + 95×0.2 + 70×0.1 = 34.8 + 22.5 + 19.0 + 7.0 = **~83**

**建议仓位** = 90 - 83×0.8 = **23.6%** → **大幅减仓，只留鱼尾** ✅ 符合预期

### 9.3 2022年10月 — 加息周期底部

| 维度 | 近似评分 |
|------|---------|
| 技术面 | ~12 |
| 波动率 | ~25 |
| 价格位置 | ~8 |
| 避险信号 | ~35 |

**综合评分** ≈ 12×0.4 + 25×0.3 + 8×0.2 + 35×0.1 = 4.8 + 7.5 + 1.6 + 3.5 = **~17**

**建议仓位** = 90 - 17×0.8 = **76.4%** → **积极加仓** ✅ 符合预期

---

## 10. 操作记录模板

每次评估后记录以下信息，用于复盘和参数调优。

```markdown
## [日期] 周度评估

### 当前指标
| 维度 | 子指标 | 原始值 | 评分 |
|------|--------|--------|------|
| 日线技术面 | SPY RSI(14) | | |
| 日线技术面 | QQQ RSI(14) | | |
| 日线技术面 | SPY MACD hist | | |
| 日线技术面 | QQQ MACD hist | | |
| 日线技术面 | SPY BB %B | | |
| 日线技术面 | QQQ BB %B | | |
| 周线技术面 | SPY Weekly RSI(14) | | |
| 周线技术面 | QQQ Weekly RSI(14) | | |
| 周线技术面 | SPY Weekly MACD hist | | |
| 周线技术面 | QQQ Weekly MACD hist | | |
| 波动率 | VIX 绝对值 | | |
| 波动率 | VIX 分位数 | | |
| 价格位置 | SPY 52w 位置 | | |
| 价格位置 | QQQ 52w 位置 | | |
| 价格位置 | SPY ATH 位置 | | |
| 价格位置 | QQQ ATH 位置 | | |
| 价格位置 | SPY MA200 偏离度 | | |
| 价格位置 | QQQ MA200 偏离度 | | |
| 量能 | SPY 量比(当日/MA20) | | |
| 量能 | QQQ 量比(当日/MA20) | | |
| 量能 | SPY 5日量能趋势 | | |
| 量能 | QQQ 5日量能趋势 | | |
| 避险 | GLD RSI(inv) | | |
| 避险 | GLD MACD(inv) | | |
| 避险 | GLD BB(inv) | | |

### 评分汇总
| 维度 | 评分 | 权重 | 加权 |
|------|------|------|------|
| 日线技术面 | | 30% | |
| 周线技术面 | | 15% | |
| 波动率 | | 25% | |
| 价格位置 | | 15% | |
| 量能确认 | | 8% | |
| 避险信号 | | 7% | |
| **综合** | **__** | | |

### 仓位决策
- 目标仓位：___%
- 当前仓位：___%
- 调仓动作：___ (加仓/减仓/不变)
- 调仓幅度：___%
- CNN Fear & Greed 参考值：___ (0-100)
- 备注：

### 实际执行
- 执行日期：
- 执行价格：
- 实际调仓幅度：
```

---

## 11. 参数调优指南

以下参数可根据实际运行情况进行调优：

| 参数 | 当前值 | 调优方向 | 说明 |
|------|--------|---------|------|
| 日线 RSI 映射区间 | [20, 80] | 可收窄至 [25, 75] | 收窄后更敏感，扩宽后更保守 |
| 日线 MACD 回溯天数 | 252 | 可缩至 126（半年） | 短回溯更灵敏，长回溯更稳定 |
| 周线 MACD 回溯 | 52 根周K | 可调为 40~60 | 周线数据点少，不宜过短 |
| VIX 映射区间 | [12, 40] | 可调为 [13, 35] | 根据近年 VIX 中枢调整 |
| ATH 回撤满分线 | -20% | 可调为 -15% 或 -25% | 更保守则用 -25%（更大回撤才满分加仓） |
| MA200 偏离度映射区间 | [-20%, +20%] | 可调为 [-15%, +15%] | 收窄后对偏离更敏感 |
| 量比恐慌阈值 | 2.5 | 可调为 2.0~3.0 | 不同标的波动特性不同 |
| 维度权重 | 30/15/25/15/8/7 | 根据回测效果微调 | 总和保持 100% |
| 单次调仓上限 | 15% | 可调为 10%~20% | 保守者用 10%，激进者用 20% |
| 冷却期 | 3 交易日 | 可调为 2~5 天 | 越短越灵敏，越长越稳定 |
| 常规仓位上下限 | [10%, 90%] | 可调为 [15%, 85%] | 更保守的选择 |
| 极端层仓位上限 | 120% | 可调为 100%~130% | 取决于融资成本和风险承受力 |

---

## 附录 A：Futu API 数据字段速查

### get_snapshot 返回字段（与评分相关）

| 字段 | 说明 | 用于 |
|------|------|------|
| `last_price` | 最新价 | 价格位置计算 |
| `high52w` | 52 周最高 | 52w 位置评分 |
| `low52w` | 52 周最低 | 52w 位置评分 |
| `prev_close_price` | 前收盘价 | 涨跌幅计算 |

### get_kline 返回字段

| 字段 | 说明 | 用于 |
|------|------|------|
| `close` | 收盘价 | RSI / MACD / BOLL / MA200 计算 |
| `high` | 最高价 | ATH 计算 |
| `volume` | 成交量 | 量能确认维度（量比 + 量能趋势） |
| `time_key` | 时间 | 数据对齐 |

---

## 附录 B：快速开始

```bash
# 1. 确保 OpenD 已启动
# 2. 一次性获取所有需要的数据

# 日K线（技术指标 + 量能，260个交易日）
python scripts/quote/get_kline.py US.SPY --ktype 1d --num 260 --json > spy_kline.json
python scripts/quote/get_kline.py US.QQQ --ktype 1d --num 260 --json > qqq_kline.json
python scripts/quote/get_kline.py US.GLD --ktype 1d --num 260 --json > gld_kline.json
python scripts/quote/get_kline.py US.VIX --ktype 1d --num 260 --json > vix_kline.json

# 周K线（周线技术面，60根周K）
python scripts/quote/get_kline.py US.SPY --ktype 1w --num 60 --json > spy_weekly.json
python scripts/quote/get_kline.py US.QQQ --ktype 1w --num 60 --json > qqq_weekly.json

# 快照（最新价、52周高低）
python scripts/quote/get_snapshot.py US.SPY US.QQQ US.GLD US.VIX --json > snapshot.json

# 3. 运行评分脚本（基于第 8 节代码实现）
# 4. 查看综合评分和建议仓位
# 5. 参考 CNN Fear & Greed (https://edition.cnn.com/markets/fear-and-greed) 作人工校验
# 6. 填写操作记录模板
```

---

## 附录 C：前后端实现规范

### C.1 整体架构

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Futu OpenD  │────▶│  FastAPI 后端      │────▶│  前端页面    │
│  (数据源)    │     │  - 定时拉取K线    │     │  - 固定文案  │
│             │     │  - 计算技术指标    │     │  - 颜色映射  │
│             │     │  - 存储 SQLite    │     │  - 仪表盘渲染│
└─────────────┘     └──────────────────┘     └─────────────┘
```

**职责划分**：

| 层 | 职责 | 变更频率 |
|---|------|---------|
| 后端 | 拉数据 → 算指标 → 算评分 → 存 SQLite → 提供 REST API | 公式调参时改 |
| 前端 | 读 JSON → 映射文案/颜色 → 渲染卡片/表格 | 几乎不动 |
| 定时任务 | 每日收盘后（美东16:00 / 北京时间04:00）触发一次计算 | 不变 |

### C.2 数据库存储（SQLite）

```sql
-- 每日评分快照
CREATE TABLE market_score (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,              -- '2026-04-30'
    composite_score REAL NOT NULL,          -- 综合评分 0~100
    target_position_pct REAL NOT NULL,      -- 目标仓位 10~120
    extreme_triggered INTEGER DEFAULT 0,    -- 是否触发极端层 0/1
    leverage_tool TEXT DEFAULT 'none',      -- 'none' / 'margin' / 'margin + OTM_call'

    -- 六维度评分
    daily_tech_score REAL,
    weekly_tech_score REAL,
    vol_score REAL,
    price_score REAL,
    volume_score REAL,
    safe_haven_score REAL,

    -- 关键原始指标（供前端展示）
    spy_price REAL,
    qqq_price REAL,
    gld_price REAL,
    vix_value REAL,
    spy_daily_rsi REAL,
    qqq_daily_rsi REAL,
    spy_weekly_rsi REAL,
    qqq_weekly_rsi REAL,
    spy_ma200_dev REAL,
    qqq_ma200_dev REAL,
    spy_vol_ratio REAL,
    qqq_vol_ratio REAL,

    created_at TEXT DEFAULT (datetime('now'))
);

-- 指标明细（JSON存储，供调试和回溯）
CREATE TABLE market_score_detail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    detail_json TEXT NOT NULL,              -- 完整 detail dict 的 JSON
    created_at TEXT DEFAULT (datetime('now'))
);
```

### C.3 后端 API 接口

#### GET /api/market-temperature

返回最新一期的市场温度评分，供首页展示。

**Response:**

```json
{
  "date": "2026-04-30",
  "update_time": "2026-04-30 04:15:00",
  "composite_score": 42.3,
  "target_position_pct": 56.2,
  "extreme_triggered": false,
  "leverage_tool": "none",
  "market_status": "略偏冷",
  "action_suggestion": "适度加仓",
  "dimensions": [
    {"key": "daily_tech", "label": "日线技术面", "score": 38.5, "weight": 0.30},
    {"key": "weekly_tech", "label": "周线技术面", "score": 45.2, "weight": 0.15},
    {"key": "volatility", "label": "波动率", "score": 52.1, "weight": 0.25},
    {"key": "price_position", "label": "价格位置", "score": 35.8, "weight": 0.15},
    {"key": "volume", "label": "量能确认", "score": 44.0, "weight": 0.08},
    {"key": "safe_haven", "label": "避险信号", "score": 55.3, "weight": 0.07}
  ],
  "indicators": {
    "SPY": {
      "price": 5320.50,
      "daily_rsi": 45.2,
      "weekly_rsi": 52.1,
      "ma200_dev": -0.031,
      "ma200_dev_pct": "-3.1%",
      "vol_ratio": 1.2,
      "bb_pct_b": 0.42
    },
    "QQQ": {
      "price": 438.20,
      "daily_rsi": 42.8,
      "weekly_rsi": 48.5,
      "ma200_dev": -0.052,
      "ma200_dev_pct": "-5.2%",
      "vol_ratio": 0.9,
      "bb_pct_b": 0.38
    },
    "GLD": {
      "price": 312.50,
      "daily_rsi": 62.3
    },
    "VIX": {
      "value": 22.5,
      "percentile_rank": 0.65,
      "abs_score": 62.5
    }
  }
}
```

#### GET /api/market-temperature/history?days=30

返回近 N 天的评分历史，用于趋势图。

```json
{
  "history": [
    {"date": "2026-04-30", "composite_score": 42.3, "target_position_pct": 56.2},
    {"date": "2026-04-29", "composite_score": 44.1, "target_position_pct": 54.7},
    ...
  ]
}
```

### C.4 前端固定文案与映射规则

前端不做任何计算，只根据后端返回的数值做**查表映射**。

#### C.4.1 市场温度文案映射

```javascript
// 综合评分 → 市场状态文案 + 颜色 + 操作建议
const TEMPERATURE_LEVELS = [
  { max: 5,   label: "极端恐慌", color: "#1a237e", bg: "#e8eaf6", action: "融资+期权超配", icon: "🟣" },
  { max: 15,  label: "极度恐慌", color: "#1a5fb4", bg: "#d0e4f5", action: "重仓逆势买入", icon: "🔵" },
  { max: 30,  label: "偏悲观",   color: "#3584e4", bg: "#dbeafe", action: "积极加仓",     icon: "🔷" },
  { max: 45,  label: "略偏冷",   color: "#62a0ea", bg: "#e0f2fe", action: "适度加仓",     icon: "❄️" },
  { max: 55,  label: "中性",     color: "#9a9996", bg: "#f5f5f5", action: "维持仓位",     icon: "⚖️" },
  { max: 70,  label: "略偏热",   color: "#ff7800", bg: "#fff3e0", action: "适度减仓",     icon: "🔶" },
  { max: 85,  label: "偏贪婪",   color: "#e66100", bg: "#fbe9e7", action: "积极减仓",     icon: "🟠" },
  { max: 100, label: "极度贪婪", color: "#c01c28", bg: "#ffebee", action: "大幅减仓",     icon: "🔴" },
];

function getTemperatureLevel(score) {
  return TEMPERATURE_LEVELS.find(level => score <= level.max);
}
```

#### C.4.2 杠杆工具文案映射

```javascript
const LEVERAGE_LABELS = {
  "none": null,  // 不显示
  "margin": {
    text: "建议融资补仓（现货ETF）",
    detail: "融资额度不超过净值30%，评分回升至45后偿还"
  },
  "margin + OTM_call": {
    text: "建议融资 + OTM Call期权超配",
    detail: "融资不超过净值30% + 权利金不超过净值10%，期权选30-60天轻度OTM(Delta 0.3-0.4)"
  }
};
```

#### C.4.3 仓位建议文案模板

```javascript
function formatPositionAdvice(data) {
  const level = getTemperatureLevel(data.composite_score);
  return {
    headline: `市场温度：${level.label}`,
    score: `综合评分 ${data.composite_score.toFixed(1)} / 100`,
    position: `建议仓位 ${data.target_position_pct.toFixed(0)}%`,
    action: level.action,
    leverage: LEVERAGE_LABELS[data.leverage_tool],
  };
}
```

#### C.4.4 维度评分条颜色映射

```javascript
// 每个维度的评分条颜色（评分越低=越恐慌=蓝色，越高=越贪婪=红色）
function getDimensionColor(score) {
  if (score <= 20) return "#1565c0";  // 深蓝
  if (score <= 40) return "#42a5f5";  // 浅蓝
  if (score <= 60) return "#9e9e9e";  // 灰色
  if (score <= 80) return "#ff9800";  // 橙色
  return "#d32f2f";                    // 红色
}
```

#### C.4.5 指标展示固定模板

首页展示三个标的的关键指标卡片，文案固定，数值从 API 填充：

```
┌─────────────────────────────────────────────────────────┐
│  📊 市场温度仪表盘          更新时间: 2026-04-30 04:15  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  综合评分: ████████░░░░░░░░░░░░  42.3 / 100            │
│  市场状态: 略偏冷 ❄️                                    │
│  建议仓位: 56%                                          │
│  操作建议: 适度加仓                                     │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  维度拆解:                                              │
│  日线技术面 [30%]  ████████░░░░  38.5                   │
│  周线技术面 [15%]  █████████░░░  45.2                   │
│  波动率    [25%]  ██████████░░  52.1                   │
│  价格位置  [15%]  ███████░░░░░  35.8                   │
│  量能确认   [8%]  █████████░░░  44.0                   │
│  避险信号   [7%]  ██████████░░  55.3                   │
│                                                         │
├──────────┬──────────┬──────────────────────────────────┤
│   SPY    │   QQQ    │   GLD          │   VIX           │
│  $5,320  │  $438.2  │  $312.5        │   22.5          │
│          │          │                │                 │
│ 日RSI 45 │ 日RSI 43 │  RSI 62        │  分位 65%       │
│ 周RSI 52 │ 周RSI 49 │                │                 │
│ MA200 -3%│ MA200 -5%│                │                 │
│ 量比 1.2x│ 量比 0.9x│                │                 │
└──────────┴──────────┴──────────┴─────┴─────────────────┘
```

### C.5 定时任务设计

```python
# scheduler.py - 每日收盘后执行
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()

@scheduler.scheduled_job('cron', hour=4, minute=15, timezone='Asia/Shanghai')
def daily_score_update():
    """
    北京时间 04:15 执行（美东 16:15，收盘后15分钟确保数据落地）
    1. 从 Futu OpenD 拉取日K线（SPY/QQQ/GLD/VIX）
    2. 从 Futu OpenD 拉取周K线（SPY/QQQ）
    3. 从 Futu OpenD 拉取快照（最新价、52周高低）
    4. 调用 calc_composite_score() 计算评分
    5. 写入 SQLite market_score 表
    6. 写入 market_score_detail 表（完整明细JSON）
    """
    pass  # 实现见第8节代码

@scheduler.scheduled_job('cron', day_of_week='sat', hour=10, minute=0, timezone='Asia/Shanghai')
def weekly_review_reminder():
    """
    每周六上午10点，生成周度评估报告（可选：推送通知）
    """
    pass
```

### C.6 实现注意事项

| 事项 | 说明 |
|------|------|
| 数据缺失处理 | Futu 拉取失败时，对应维度评分设为 50（中性），前端显示"数据待更新" |
| 非交易日 | 周末/节假日不执行计算，API 返回最近一个交易日的数据 |
| 首次部署 | 需一次性拉取 260 日K + 60 周K 的历史数据初始化 |
| ATH 数据 | 首次部署时拉取 5 年日K 计算 ATH，后续每日更新 max(ATH, today_high) |
| 前端缓存 | 评分每天只更新一次，前端可缓存至次日凌晨 |
| API 限流 | Futu OpenD 有频率限制，批量拉取时每个请求间隔 1 秒 |
