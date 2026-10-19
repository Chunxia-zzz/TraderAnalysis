# 市场仓位管理策略框架

> 版本：v1.0 | 创建日期：2026-04-30
> 数据源：Futu OpenAPI | 评估频率：周频
> 最近核对：2026-10-12（对照 `market_scorer.py` / `config.py` 逐条核对；本文档描述的策略框架为主，实际生效口径以代码为准）
>
> **⚠️ 重要说明**：本文档最初按「六维度」设计。截至 2026-10-12，**实际代码已简化为三维度**（日线技术面 50% + 周线技术面 35% + 价格位置 15%），**波动率(VIX)、量能确认、避险信号(GLD) 三个维度已从市场温度评分中移除**（相关章节保留原设计构想并加标注）。此外，黄金/比特币已拆分为**独立的单资产温度**（见第 4.7 节）。
>
> **⚠️ 口径反转（2026-10-19）**：市场温度分数已**镜像反转**——新口径为「**市场越恐慌 → 综合评分越高 → 仓位越高**」，
> 与个股评分 `total_score`（高分=值得加仓）同向。本文档正文中所有「评分越低=恐慌」的方向描述均为旧口径，
> 阈值区间也已镜像（极端层 85/75、状态表 95/85/70/55/45/30/15），以 `market_scorer.py` / `docs/api.md` 为准；
> 仓位映射与个股温度加成与旧口径**数学等价**（决策输出逐位不变）。

---

## 1. 策略概述

### 1.1 目标

根据市场技术指标和情绪冷热程度，量化评估当前市场状态，输出建议仓位水平。**用数字约束人性**——恐慌时敢于逆势加仓，贪婪时纪律性减仓只留鱼尾。

### 1.2 核心逻辑

```
市场越恐慌 → 综合评分越高 → 仓位越高（逆势加仓）    ← 2026-10-19 口径反转后
市场越贪婪 → 综合评分越低 → 仓位越低（纪律减仓）
```

> 旧口径（≤2026-10-19 前）为「评分越低=恐慌」，已镜像反转；阈值区间同步镜像（极端层 85/75，状态表 95/85/70/55/45/30/15），仓位映射数学等价。

### 1.3 适用范围

| 项目 | 说明 |
|------|------|
| 投资标的 | 美股权益类（SPY/QQQ 为主） |
| 评估频率 | 每周一次（周日晚/周一盘前） |
| 仓位范围 | 30% ~ 120%（目标仓位映射输出下限为 30%；>90% 起出现杠杆工具建议，>100% 进入杠杆区） |
| 持仓周期 | 中长线（周级别调仓） |

> 核对：仓位映射下限为 30%（`market_scorer.py:287` `_clamp(..., 30, 85)`）。原文档写作「10% ~ 120%」，与实现不符，已更正。`leverage_tool` 在目标仓位 >90% 时给出 `margin`、>100% 时给出 `margin + OTM_call`（`market_scorer.py:290-294`）。

---

## 2. 监控标的与数据源

### 2.1 核心标的

| 标的 | Futu 代码 | 角色 | 说明 |
|------|----------|------|------|
| S&P 500 ETF | `US.SPY` | 大盘代表 | 反映美股整体水温 |
| Nasdaq 100 ETF | `US.QQQ` | 科技成长代表 | 通常比 SPY 波动更大，更早反映风险偏好 |
| Gold ETF | `US.GLD` | 避险情绪代理 | GLD 走强通常意味 risk-off |
| VIX 恐慌指数 | `US.VIX` | 波动率/恐慌度 | 市场的"恐惧温度计" |

> ⚠️ **状态：市场温度评分仅使用 SPY + QQQ**（`config.py:194` `MARKET_TEMP_CODES = ["US.SPY", "US.QQQ"]`；`config.py:191-193` 明确「VIX 期货由用户肉眼观察，不纳入算法」）。**GLD / VIX 不再参与市场温度评分**——GLD 改为独立的单资产温度（第 4.7 节），VIX 仅作为人工参考。原「避险信号(GLD)」「波动率(VIX)」两个评分维度已从 `market_scorer.py` 中移除（源码注释：`market_scorer.py:231-232`「历史版本曾含 GLD/VIX 避险维度，现已简化为 3 维度」）。

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

> 注：上表为粗粒度方向示意。代码中精确的状态分档为 `5 / 15 / 30 / 45 / 55 / 70 / 85 / 100`（`market_scorer.py:23-32`，与 C.4.1 一致）。

### 3.1 三大评分维度与权重

```
综合评分 = 日线技术面(50%) + 周线技术面(35%) + 价格位置(15%)
```

| 维度 | 权重 | 输入标的 | 核心逻辑 |
|------|------|---------|---------|
| 日线技术面 | 50% | SPY + QQQ | 日线 RSI/MACD/BOLL 判断超买超卖 |
| 周线技术面 | 35% | SPY + QQQ | 周线 RSI/MACD/BOLL 过滤日线噪音，确认大级别方向 |
| 价格位置 | 15% | SPY + QQQ | 52 周位置 + ATH 回撤 + MA200 偏离度 |

> 核对：与 `config.py:196-200` `MARKET_TEMP_WEIGHTS`（daily_tech 0.50 / weekly_tech 0.35 / price_pos 0.15）一致，加权求和见 `market_scorer.py:258-262`。
> 已更新：原为六维度「30/15/25/15/8/7」；现为三维度「50/35/15」，波动率、量能、避险三维度已从代码移除。

> **权重设计理由**：
> - 日线技术面（50%）：最直接的超买超卖信号，是市场温度的主导维度
> - 周线技术面（35%）：过滤日线噪音，日线 RSI 可能反复超卖但周线还没到位（如 2022 持续阴跌），是判断"跌够没有"的关键
> - 价格位置（15%）：52 周位置 + ATH 回撤 + MA200 偏离度，提供均值回归视角
> - ~~波动率（原 25%）/ 量能确认（原 8%）/ 避险信号（原 7%）~~：**已从市场温度评分中移除**（见 4.3 / 4.5 / 4.6 节标注）

---

## 4. 各维度评分规则

### 4.1 日线技术面维度（权重 50%）

对 **SPY** 和 **QQQ** 分别计算以下三个子指标，共 6 个评分，取算术平均。

#### 4.1.1 RSI(6) 分档评分

**参数**：周期 = 6 日（代码使用 `rsi6` 列，非 RSI(14)）

**映射公式**（分档制，每 10 点一档）：

```
RSI_score = clamp(floor(RSI / 10) × 10,  0,  100)
```

即 RSI 落在哪一「十位档」，评分就取该档的整十值。

| RSI 值 | 评分 | 市场状态 |
|--------|------|---------|
| < 10 | 0 | 极度超卖，恐慌性抛售 |
| 10 ~ 19 | 10 | 极度超卖 |
| 20 ~ 29 | 20 | 深度超卖区 |
| 30 ~ 39 | 30 | 超卖区 |
| 40 ~ 49 | 40 | 偏冷 |
| 50 ~ 59 | 50 | 中性 |
| 60 ~ 69 | 60 | 偏热 |
| 70 ~ 79 | 70 | 超买区 |
| 80 ~ 89 | 80 | 极度超买 |
| ≥ 90 | 90 | 极端 FOMO |

> 已更新：原为「RSI(14) + 线性映射 `(RSI-20)/60×100`」；现为「RSI(6) + 分档映射 `int(rsi/10)*10`」。证据：`config.py:120` `"rsi": [6, 12, 24]`；`market_scorer.py:81-82`（日线）与 `123-124`（周线）`rsi = ...get("rsi6", 50); rsi_score = _clamp(int(rsi / 10) * 10.0)`。
> 注：分档映射下 RSI 不到 90 时评分上限为 90，不存在「≥90 得 100」的旧口径。

#### 4.1.2 MACD(12,26,9) 柱状图评分

**参数**：快线 = 12，慢线 = 26，信号线 = 9

**评分方法**：使用 MACD 柱状图（histogram = DIF - DEA）在**过去 252 个交易日**中的百分位排名。

```
MACD_score = percentile_rank(current_histogram, lookback=252) × 100
```

> 核对：与 `market_scorer.py:88-91` 一致（`_percentile_rank(df["macd"], macd_current, 252) * 100`）。注：代码中 `macd = (dif - dea) * 2`（`indicators.py:46`，乘 2 对齐富途显示口径），但百分位排名与倍数无关，结果不受影响。

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

> 核对：与 `market_scorer.py:99-100` 一致（`pct_b` 由存储列 `boll_upper/boll_lower` 计算，`bb_score = _clamp(pct_b * 100)`）。

#### 4.1.4 日线技术面综合评分

```
daily_tech_score = (SPY_RSI + QQQ_RSI + SPY_MACD + QQQ_MACD + SPY_BB + QQQ_BB) / 6
```

> 核对：与 `market_scorer.py:70-106` 一致（6 项算术平均）。

---

### 4.2 周线技术面维度（权重 35%）

对 **SPY** 和 **QQQ** 的**周线 K 线**分别计算 RSI、MACD 和 BOLL，共 6 个评分，取算术平均。

> 已更新：原为「权重 15%、RSI + MACD 共 4 项」；现为「权重 35%、RSI + MACD + BOLL 共 6 项」。证据：`config.py:199` `"weekly_tech": 0.35`；`market_scorer.py:112-148`（周线含 `Weekly_BB` 子项）。

> **数据需求**：需要约 60 根周 K 线（≈ 1.2 年），Futu API 获取方式：
> ```bash
> python scripts/quote/get_kline.py US.SPY --ktype 1w --num 60 --json
> python scripts/quote/get_kline.py US.QQQ --ktype 1w --num 60 --json
> ```

#### 4.2.1 周线 RSI(6) 分档评分

**参数**：周期 = 6（周线同样使用 `rsi6` 列）

**映射公式**（与日线相同，分档制）：

```
Weekly_RSI_score = clamp(floor(Weekly_RSI / 10) × 10,  0,  100)
```

| 周线 RSI 值 | 评分 | 市场状态 |
|------------|------|---------|
| < 10 | 0 | 极度超卖（罕见，非常极端） |
| 20 ~ 29 | 20 | 周级别超卖，大级别底部信号 |
| 40 ~ 49 | 40 | 偏弱 |
| 50 ~ 59 | 50 | 中性 |
| 60 ~ 69 | 60 | 偏强 |
| 70 ~ 79 | 70 | 周级别超买 |
| ≥ 90 | 90 | 极度超买（牛市末期） |

> 已更新：原为「周线 RSI(14) + 线性映射」；现为「RSI(6) + 分档映射」，与日线同一函数（`market_scorer.py:122-124`）。

> **周线 RSI vs 日线 RSI 的区别**：宽指 ETF 周线 RSI 极少低于 30（只在 2008、2011、2020、2022 出现过），一旦到 30 以下基本是大级别底部区域。日线 RSI 到 30 则较常见，可能只是正常回调。

#### 4.2.2 周线 MACD(12,26,9) 柱状图评分

**评分方法**：与日线相同，使用百分位排名，但回溯窗口为 **52 根周 K**（约 1 年）。

```
Weekly_MACD_score = percentile_rank(weekly_histogram, lookback=52) × 100
```

> 核对：与 `market_scorer.py:129-133` 一致。

#### 4.2.3 周线布林带 %B 评分

**参数**：周期 = 20 周，标准差倍数 = 2

**映射公式**（与日线相同）：

```
Weekly_BB_score = clamp(Weekly_%B × 100,  0,  100)
```

> 已新增：原设计「周线不加布林带」，现代码已加入周线 %B 子项（`market_scorer.py:137-145`）。周线与日线共用存储列 `boll_upper/boll_lower`（周线由 `WEEKLY_INDICATOR_CONFIG` 计算，见 `config.py:132`）。

#### 4.2.4 周线技术面综合评分

```
weekly_tech_score = (SPY_Weekly_RSI + QQQ_Weekly_RSI + SPY_Weekly_MACD
                   + QQQ_Weekly_MACD + SPY_Weekly_BB + QQQ_Weekly_BB) / 6
```

> 核对：与 `market_scorer.py:112-148` 一致（6 项算术平均）。

---

### 4.3 波动率维度（权重 25%）

> ⚠️ **状态：设计构想，代码中未实现**（截至 2026-10-12 在 `market_scorer.py` / `config.py` 中未找到对应实现。VIX 不参与市场温度评分——`config.py:191-193`「VIX 期货由用户肉眼观察，不纳入算法」；`market_scorer.py:354` 中 `vol_score` 恒为 `None`）。本节数值为 v1.0 设计口径，保留备查。

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
drawdown = (ATH - Price) / ATH           # 0 表示在ATH，0.15 表示回撤 15%
ATH_score = clamp((1 - drawdown / 0.15) × 100,  0,  100)
```

| 距 ATH 回撤幅度 | 评分 | 含义 |
|----------------|------|------|
| 0%（创新高） | 100 | 价格在历史最高，可能过热 |
| -3.75% | 75 | 小幅回调 |
| -7.5% | 50 | 技术性回调 |
| -11.25% | 25 | 较深回调 |
| ≥ -15% | 0 | 进入技术性熊市区间 |

> 已更新：零分线原为回撤 20%，现为 **15%**。证据：`market_scorer.py:180-182` `ath = df["high"].max(); ath_score = _clamp((1 - drawdown / 0.15) * 100)`（大盘回撤 15% 即视为极端恐慌）。注：代码 ATH 取**全部已入库 K 线**的 `high` 最大值（非固定 5 年窗口）。
> 单资产（黄金/比特币）零分线不同，见第 4.7 节。

> **ATH 数据获取**：Futu 快照不直接提供 ATH，可通过拉取较长历史 K 线（如 5 年日 K）取最高收盘价计算：
> ```bash
> python scripts/quote/get_kline.py US.SPY --ktype 1d --start 2021-01-01 --end 2026-04-30 --json
> ```

#### 4.4.3 MA200 偏离度评分

**定义**：当前价格相对 200 日均线的偏离程度。

```
MA200_dev = (Price - MA200) / MA200
MA200_score = clamp((MA200_dev + 0.15) / 0.30 × 100,  0,  100)
```

| MA200 偏离度 | 评分 | 含义 |
|-------------|------|------|
| ≤ -15% | 0 | 极度偏离均线下方（恐慌性超跌，均值回归动能强） |
| -7.5% | 25 | 显著低于均线 |
| 0%（在MA200上） | 50 | 中性 |
| +7.5% | 75 | 显著高于均线 |
| ≥ +15% | 100 | 极度偏离均线上方（过热，回归压力大） |

> 已更新：映射区间原为 `[-20%, +20%]`（跨度 0.40），现为 **`[-15%, +15%]`（跨度 0.30）**。证据：`market_scorer.py:196` `ma200_score = _clamp((deviation + 0.15) / 0.30 * 100)`。
> 单资产（黄金/比特币）映射区间不同，见第 4.7 节。

> **为什么加 MA200 偏离度？** 52 周位置和 ATH 回撤只告诉你"从高点跌了多少"，但不能区分"均线本身也在下行（趋势破坏）"vs"价格急跌远离均线（超跌反弹概率高）"。偏离度捕捉的是均值回归的弹性空间。

#### 4.4.4 价格位置综合评分

```
price_score = (SPY_52w + QQQ_52w + SPY_ATH + QQQ_ATH + SPY_MA200 + QQQ_MA200) / 6
```

> 核对：与 `market_scorer.py:154-202` 一致（52 周位置取近 252 根的 high/low，6 项算术平均）。

---

### 4.5 量能确认维度（权重 8%）

> ⚠️ **状态：设计构想，代码中未实现**（截至 2026-10-12 在 `market_scorer.py` / `config.py` 中未找到对应实现。`market_scorer.py:356` 中 `volume_score` 恒为 `None`）。本节阈值/分档为 v1.0 设计口径，保留备查。

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

> ⚠️ **状态：设计构想，代码中未实现**（截至 2026-10-12 在 `market_scorer.py` / `config.py` 中未找到对应实现。GLD 已不再作为市场温度的避险子维度，`market_scorer.py:357` 中 `safe_haven_score` 恒为 `None`）。GLD 现改为**独立的单资产温度**（见第 4.7 节，取值为绝对的黄金自身冷热，而非对权益市场的反向映射）。本节为 v1.0 设计口径，保留备查。

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

> **局限性说明**：GLD 受黄金供需、美元指数、实际利率、央行购金等多因素影响，并非纯粹的避险指标。（本节已随维度移除而废弃，见上方状态标注。）

---

### 4.7 单资产温度（黄金 / 比特币）

> ✅ 已实现（截至 2026-10-12）。原文档未描述单资产温度，此处据 `market_scorer.py:compute_asset_temperature` 补充。

单资产温度复用三维度框架（日线技术面 50% + 周线技术面 35% + 价格位置 15%），但**阈值按资产波动特性独立校准**：

| 资产 | key | 代码 | ATH 回撤零分线 | MA200 偏离映射区间 |
|------|-----|------|---------------|-------------------|
| 黄金 | `GLD` | `US.GLD` | 25% | ±20% |
| 比特币 | `BTC` | `US.IBIT` | 50% | ±60% |

- 黄金：`ath_drawdown_zero = 0.25`、`ma200_range = 0.20`（黄金正常回调幅度较大）——`market_scorer.py:400-406`
- 比特币：`ath_drawdown_zero = 0.50`、`ma200_range = 0.60`（BTC 腰斩为常态）——`market_scorer.py:407-414`。注：IBIT 上市于 2024 年初，历史样本有限，百分位置信度较低。
- 与大盘温度不同，单资产**没有极端层判定、没有仓位映射**，只输出评分（0~100）与状态文案；RSI 同样使用 `rsi6` 分档（`market_scorer.py:418-475`）。
- 入口：`GET /api/market-temperature`（响应附加 `gld_temp` / `btc_temp`）、`GET /api/asset-temperature/history?asset=GLD|BTC`（`api_server.py:444-466`）。

---

## 5. 综合评分与仓位映射

### 5.1 综合评分公式

```
composite = daily_tech_score × 0.50
          + weekly_tech_score × 0.35
          + price_score       × 0.15
```

> 核对：与 `market_scorer.py:258-262` 一致（三维度加权，权重取自 `config.py:196-200`）。

### 5.2 仓位映射公式（三层）

仓位范围 **30% ~ 120%**，总跨度 90%。美股长牛前提下，最低 30% 保证不踏空，极端恐慌时上杠杆抄底。

**正常区（composite > 25）：**

```
target_position(%) = 85 - (composite - 25) × (55 / 75)
钳位 [30%, 85%]
```

**轻度极端（composite ≤ 25，未满足重度条件）：**

```
target_position(%) = 85 + (25 - composite) × (15 / 10)
钳位 [85%, 100%]
```

**重度极端（composite ≤ 15 AND SPY日RSI<30 AND SPY周RSI<30）：**

```
target_position(%) = 100 + (15 - composite) × (20 / 15)
钳位 [100%, 120%]
```

> 核对：三段映射与 `market_scorer.py:279-287` 逐字一致（`heavy_extreme` / `light_extreme` / 正常区）。极端条件中 RSI 为 **RSI(6)**（`market_scorer.py:265-266` 取 `rsi6`）。

| 综合评分 | 市场状态 | 目标仓位 | 操作建议 |
|---------|---------|---------|---------|
| 0 ~ 15 | 重度极端（RSI达标） | 100% ~ 120% | 融资 + 期权超配 |
| 15 ~ 25 | 轻度极端 | 85% ~ 100% | 重仓逆势买入，分批抄底 |
| 25 ~ 40 | 偏悲观 | 74% ~ 85% | 积极加仓 |
| 40 ~ 55 | 略偏冷 | 63% ~ 74% | 适度加仓 |
| 55 ~ 65 | 中性 | 56% ~ 63% | 维持仓位 |
| 65 ~ 80 | 略偏热 | 45% ~ 56% | 适度减仓 |
| 80 ~ 90 | 偏贪婪 | 37% ~ 45% | 积极减仓 |
| 90 ~ 100 | 极度贪婪 | 30% ~ 37% | 减至底仓 |

> 已更新：65~80 / 80~90 / 90~100 三档目标仓位原为「41%~56% / 34%~41% / 30%~34%」，按当前映射公式 `85 - (composite-25) × (55/75)` 重算为「45%~56% / 37%~45% / 30%~37%」（原值系旧映射口径遗留）。

### 5.3 极端层触发条件（两级）

**轻度极端（进入 85%~100% 仓位区）：**

| # | 条件 | 理由 |
|---|------|------|
| 1 | 综合评分 ≤ 25 | 系统确认市场偏恐慌 |

**重度极端（进入杠杆区 100%~120%）需同时满足：**

| # | 条件 | 理由 |
|---|------|------|
| 1 | 综合评分 ≥ 85 | 系统已确认极度恐慌（2026-10-19 口径反转：高分=恐慌） |
| 2 | SPY **周线** RSI(6) < 30 | 周级别超卖确认，非日内噪音 |
| 3 | SPY **日线** RSI(6) < 30 | 日级别深度超卖 |

> 核对：与 `market_scorer.py:287-292` 一致（`heavy_extreme = composite >= 85 and spy_daily_rsi < 30 and spy_weekly_rsi < 30`，`light_extreme = composite >= 75`，RSI 取 `rsi6`；2026-10-19 口径反转，与旧 `<=15/<=25` 镜像等价）。**注意：代码中重度极端不再要求 VIX 条件**（旧 v1.0 曾含 `vix_current > 35`，现已移除）。

**极端层内部分级：**

| 仓位目标 | 层级 | 执行工具 |
|---------|------|---------|
| 85% ~ 100% | 轻度极端 | 现金满仓买入 ETF |
| 100% ~ 110% | 重度极端 | **融资买入** + 轻度 OTM Call |
| 110% ~ 120% | 重度极端（composite接近100） | 融资满额 + 加大期权仓位 |

### 5.4 底部确认辅助信号（不参与公式计算，人工参考）

以下信号不纳入评分公式，但在极端层触发后可作为**择时加仓的辅助确认**：

| 信号 | 定义 | 确认含义 |
|------|------|---------|
| RSI 底背离 | 价格创新低，但日线 RSI(6) 未创新低 | 下跌动能衰竭，底部概率高 |
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
120%|■                          ← 重度极端：融资+期权（composite≤15 + RSI达标）
    |■■
110%|■■■
    |■■■■
100%|■■■■■ ─ ─ ─ ─ ─ ─ ─ ─ ─  ← 杠杆线（重度极端入口）
    |■■■■■■
 90%|■■■■■■■
    |■■■■■■■■
 85%|■■■■■■■■■ ─ ─ ─ ─ ─ ─ ─  ← 轻度极端入口（composite≤25）
    |■■■■■■■■■■
 70%|■■■■■■■■■■■■
    |■■■■■■■■■■■■■
 60%|■■■■■■■■■■■■■■■            ← 中性偏上（composite≈50 → 67%）
    |■■■■■■■■■■■■■■■■
 50%|■■■■■■■■■■■■■■■■■
    |■■■■■■■■■■■■■■■■■■
 40%|■■■■■■■■■■■■■■■■■■■
    |■■■■■■■■■■■■■■■■■■■■
 30%|■■■■■■■■■■■■■■■■■■■■■      ← 底仓（极度贪婪时最低保持30%）
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
| 最低仓位 | **30%** | 保留底仓防踏空（正常区映射下限，`market_scorer.py:287` 钳位 `[30, 85]`） |
| 常规最高仓位 | **85%** | 保留现金作安全垫和加仓弹药（正常区映射上限） |
| 杠杆区最高仓位 | **120%** | 需满足极端触发条件（见 5.3 节） |
| 融资上限 | 净值 **30%** | 控制爆仓风险 |
| 期权上限 | 净值 **10%**（权利金） | 亏损封顶 |

> 已更新：最低仓位原为 10%，现为 **30%**（与代码映射下限一致）；常规最高仓位原为 90%，现为 **85%**（正常区映射上限；>90% 已是轻度极端区）。

---

## 7. 特殊情况处理

### 7.1 数据缺失

某个指标数据获取失败时，该指标评分设为 **50（中性）**，权重不变。

> 核对：与 `market_scorer.py:210-219` `_safe_score` 一致（维度计算异常时返回 `NEUTRAL_SCORE = 50`，见 `market_scorer.py:34`）。

```
例：VIX 数据获取失败
→ VIX_abs_score = 50, VIX_pct_score = 50
→ vol_score = 50
→ 其余维度正常计算
```

### 7.2 极端行情加速规则

> ⚠️ **状态：设计构想，代码中未实现**（截至 2026-10-12 在 `market_scorer.py` / `allocation.py` 中未找到自动调仓/分批限制逻辑，本节为人工执行规则）。

| 触发条件 | 特殊规则 |
|---------|---------|
| SPY 或 QQQ 单日暴跌 > 5% | 忽略冷却期 + 单次调仓上限放宽至 **25%** |
| 综合评分 < 10 持续 3 天以上 | 可一次性调仓至目标仓位（忽略分批限制） |

### 7.3 GLD 与 SPY/QQQ 同向异常

> ⚠️ **状态：设计构想，代码中未实现**（截至 2026-10-12 在 `market_scorer.py` / `config.py` 中未找到对应实现。GLD 已移出市场温度评分，不存在「避险权重减半」的实现）。

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

> ⚠️ **状态：v1.0 参考实现，与当前代码不一致。** 本节为文档最初附带的示例代码，**并非项目实际运行的代码**。当前实现位于 `market_scorer.py` + `indicators.py`，主要差异如下（详见各小节标注）：
>
> | 项 | 本节示例（v1.0） | 当前实现 |
> |----|------------------|---------|
> | 评分维度 | 六维度 30/15/25/15/8/7 | 三维度 50/35/15 |
> | RSI | `calc_rsi(period=14)`，线性映射 `(RSI-20)/60×100` | `rsi6`（周期 6），分档映射 `int(rsi/10)*10` |
> | 周线技术面 | RSI + MACD（4 项） | RSI + MACD + BB（6 项） |
> | ATH 零分线 | 20% | 15% |
> | MA200 映射区间 | ±20%（跨度 0.40） | ±15%（跨度 0.30） |
> | 仓位映射 | 两段（`90-c×0.8` / `90+(15-c)×2`） | 三段（正常区 / 轻度极端 / 重度极端） |
> | 极端条件 | `composite<=15 and spy_rsi<25 and weekly_rsi<30 and vix>35` | `composite<=15 and spy_daily_rsi<30 and spy_weekly_rsi<30`（无 VIX） |

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
    """MA200偏离度映射到评分 (偏离 -15%→0分, 0%→50分, +15%→100分)"""
    return clamp((deviation + 0.15) / 0.30 * 100)
```

> 已更新：映射区间原为 `±20% / 0.40`，现为 `±15% / 0.30`（`market_scorer.py:196`）。

### 8.6 量能评分计算

> ⚠️ **状态：设计构想，代码中未实现**（量能维度已从市场温度评分移除，见 4.5 节）。

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

    # === 日线技术面 (50%) ===   # 已更新：原 30%
    # 已更新：实际用 rsi6 与分档映射 int(rsi/10)*10；下方线性映射为 v1.0 旧口径
    spy_rsi = calc_rsi(spy_closes).iloc[-1]
    qqq_rsi = calc_rsi(qqq_closes).iloc[-1]
    spy_rsi_score = clamp(int(spy_rsi / 10) * 10)   # 旧：clamp((spy_rsi - 20) / 60 * 100)
    qqq_rsi_score = clamp(int(qqq_rsi / 10) * 10)   # 旧：clamp((qqq_rsi - 20) / 60 * 100)

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

    # === 周线技术面 (35%) ===   # 已更新：原 15%（且现含周线 BB，共 6 项）
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
    spy_ath_score = clamp((1 - spy_dd / 0.15) * 100)   # 已更新：零分线 20% → 15%
    qqq_ath_score = clamp((1 - qqq_dd / 0.15) * 100)
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
    # 已更新：当前为三维度加权（与 market_scorer.py:258-262 一致）
    composite = (daily_tech_score * 0.50 + weekly_tech_score * 0.35 +
                 price_score * 0.15)

    # === 极端层判断（两级，2026-10-19 口径反转：高分=恐慌）===
    # 已更新：heavy 不再要求 VIX；RSI 阈值为 30（market_scorer.py:287-292）
    heavy_extreme = (composite >= 85 and spy_rsi < 30 and spy_weekly_rsi < 30)
    light_extreme = composite >= 75 and not heavy_extreme
    extreme_triggered = heavy_extreme or light_extreme

    # 已更新：三段映射（market_scorer.py _map_position；2026-10-19 口径反转，与旧公式逐位等价）
    if heavy_extreme:
        target_position = clamp(100 + (composite - 85) * (20.0 / 15), 100, 120)
    elif light_extreme:
        target_position = clamp(85 + (composite - 75) * (15.0 / 10), 85, 100)
    else:
        target_position = clamp(30 + composite * (55.0 / 75), 30, 85)

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

> ⚠️ **状态：示例基于 v1.0 旧口径，与当前实现不一致。** 本节各例的「综合评分」均按**四维权重 `技术面×0.4 + 波动率×0.3 + 价格位置×0.2 + 避险×0.1`** 与旧仓位公式 `90 - composite×0.8` 计算，且 RSI 用 RSI(14)。当前实现为**三维度 50/35/15** + 三段映射（见第 5 节），维度名称与权重均已变化。以下数值仅作历史量级参考，**不可直接与现行系统输出比较**。

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

> ⚠️ **注**：上表中「波动率 / 量能 / 避险」三类子指标已不再参与市场温度评分（见 4.3 / 4.5 / 4.6 节），仅保留供人工记录参考。RSI 实际口径为 **RSI(6)** 分档（见 4.1.1），非 RSI(14)。

### 评分汇总
| 维度 | 评分 | 权重 | 加权 |
|------|------|------|------|
| 日线技术面 | | 50% | |
| 周线技术面 | | 35% | |
| 价格位置 | | 15% | |
| **综合** | **__** | | |

> 已更新：原为六维度 30/15/25/15/8/7，现为三维度 50/35/15（`config.py:196-200`）。

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
| 日线/周线 RSI 周期 | 6（`rsi6`） | 可改为 12 / 24 | `config.py:120,130` `"rsi": [6, 12, 24]`，代码取 `rsi6` |
| RSI 评分档宽 | 每 10 点一档 | 可改为 5 点/20 点一档 | `market_scorer.py:82` `int(rsi/10)*10` |
| 日线 MACD 回溯天数 | 252 | 可缩至 126（半年） | 短回溯更灵敏，长回溯更稳定 |
| 周线 MACD 回溯 | 52 根周K | 可调为 40~60 | 周线数据点少，不宜过短 |
| ~~VIX 映射区间~~ | ~~[12, 40]~~ | ❌ 未实现 | VIX 未参与评分（见 4.3 节） |
| ATH 回撤零分线 | -15% | 可调为 -10% 或 -20% | `market_scorer.py:182`（大盘）；黄金 25% / BTC 50% |
| MA200 偏离度映射区间 | [-15%, +15%] | 可调为 [-20%, +20%] | `market_scorer.py:196`（大盘）；黄金 ±20% / BTC ±60% |
| ~~量比恐慌阈值~~ | ~~2.5~~ | ❌ 未实现 | 量能维度未参与评分（见 4.5 节） |
| 维度权重 | 50/35/15 | 根据回测效果微调 | 总和保持 100% |
| 单次调仓上限 | 15% | 可调为 10%~20% | 保守者用 10%，激进者用 20%（人工规则，代码未实现） |
| 冷却期 | 3 交易日 | 可调为 2~5 天 | 越短越灵敏，越长越稳定（人工规则，代码未实现） |
| 常规仓位上下限 | [30%, 85%] | 可调为 [40%, 80%] | 更保守的选择（`market_scorer.py:287`） |
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

    -- 评分维度（现为三维度；vol/volume/safe_haven 恒为 NULL）
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

> 核对：表结构与 `storage.py:69-102` 完全一致。**但注意字段口径变化**：由于市场温度已简化为三维度，`vol_score` / `volume_score` / `safe_haven_score` / `gld_price` / `vix_value` 五个字段现恒写入 `NULL`（`market_scorer.py:354-361`）；另新增的 `extreme_level`（`"none"/"light"/"heavy"`）字段**未落库**，仅在 API 内存返回（`market_scorer.py:345`）。

### C.3 后端 API 接口

#### GET /api/market-temperature

返回最新一期的市场温度评分，供首页展示。

**Response（示意；实际返回为 `market_score` 表行 + `detail` 明细，另附加 `gld_temp` / `btc_temp`）：**

```json
{
  "date": "2026-04-30",
  "composite_score": 42.3,
  "target_position_pct": 72.3,
  "extreme_triggered": false,
  "leverage_tool": "none",
  "market_status": "略偏冷",
  "action_suggestion": "适度加仓",
  "extreme_level": "none",
  "dimensions": [
    {"key": "daily_tech", "label": "日线技术面", "score": 38.5, "weight": 0.50},
    {"key": "weekly_tech", "label": "周线技术面", "score": 45.2, "weight": 0.35},
    {"key": "price_position", "label": "价格位置", "score": 35.8, "weight": 0.15}
  ],
  "indicators": {
    "SPY": {
      "price": 532.50,
      "daily_rsi": 45.2,
      "weekly_rsi": 52.1,
      "ma200_dev": -0.031,
      "vol_ratio": 1.2,
      "bb_pct_b": 0.42
    },
    "QQQ": {
      "price": 438.20,
      "daily_rsi": 42.8,
      "weekly_rsi": 48.5,
      "ma200_dev": -0.052,
      "vol_ratio": 0.9,
      "bb_pct_b": 0.38
    }
  },
  "gld_temp": {"label": "黄金", "composite_score": 61.4, "market_status": "略偏热"},
  "btc_temp": {"label": "比特币 (IBIT)", "composite_score": 55.0, "market_status": "中性"}
}
```

> 已更新：原示例含六维度（含 volatility/volume/safe_haven）、`GLD`/`VIX` 指标块，且 `target_position_pct: 56.2`；现改为三维度，并按当前映射 `85 - (42.3-25) × (55/75) = 72.3` 修正目标仓位。注：`dimensions` / `market_status` / `action_suggestion` / `indicators` 由 `market_scorer._compute_score` 组装（`market_scorer.py:303-333`），**但 `GET /api/market-temperature` 直接返回 `storage.query_latest_market_score()` 的库表行 + `detail`**（`api_server.py:438-446`），上述数组字段是否透出取决于部署的前端；以实际接口返回为准。

#### GET /api/market-temperature/history?days=30

返回近 N 天的评分历史，用于趋势图。

```json
{
  "history": [
    {"date": "2026-04-30", "composite_score": 42.3, "target_position_pct": 72.3},
    {"date": "2026-04-29", "composite_score": 44.1, "target_position_pct": 71.0},
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
// 每个维度的评分条颜色（2026-10-19 口径反转后：评分越高=越恐慌=蓝色，越低=越贪婪=红色）
function getDimensionColor(score) {
  if (score >= 80) return "#1565c0";  // 深蓝
  if (score >= 60) return "#42a5f5";  // 浅蓝
  if (score >= 40) return "#9e9e9e";  // 灰色
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
│  建议仓位: 72%                                          │
│  操作建议: 适度加仓                                     │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  维度拆解:                                              │
│  日线技术面 [50%]  ████████░░░░  38.5                   │
│  周线技术面 [35%]  █████████░░░  45.2                   │
│  价格位置  [15%]  ███████░░░░░  35.8                   │
│                                                         │
├──────────┬──────────┬──────────────────────────────────┤
│   SPY    │   QQQ    │   黄金(GLD)    │   比特币(IBIT)  │
│  $532.5  │  $438.2  │  $312.5        │   $45.8         │
│          │          │                │                 │
│ 日RSI 45 │ 日RSI 43 │  温度 61.4     │   温度 55.0     │
│ 周RSI 52 │ 周RSI 49 │                │                 │
│ MA200 -3%│ MA200 -5%│                │                 │
│ 量比 1.2x│ 量比 0.9x│                │                 │
└──────────┴──────────┴──────────┴─────┴─────────────────┘
```

> 已更新：原模板为六维度 + GLD/VIX 指标列、建议仓位 56%；现改为三维度 + 黄金/比特币单资产温度列、建议仓位 72%（`85 - (42.3-25) × (55/75)`）。

### C.5 定时任务设计

> ⚠️ **状态：设计构想，代码中未实现**（截至 2026-10-12 全局未找到 APScheduler / `scheduler.py`）。实际日更由 `scripts/daily_sync.bat` 通过系统计划任务触发，依次执行 `python -m trader_analysis update` → `temperature` → `score` → `scan-signals`，并把 `data/indicators.db` scp 到服务器。下方 `scheduler.py` 仅为设计示意。

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
| ATH 数据 | ⚠️ 已更新：实际不拉 5 年日K。ATH = **已入库日线**的 `high` 最大值，而 `calculate_market_temperature` 仅读最近 300 根（`market_scorer.py:381` `limit=300`），故 ATH 实为「近约 300 个交易日（~1.2 年）内最高」，并非历史最高。 |
| 前端缓存 | 评分每天只更新一次，前端可缓存至次日凌晨 |
| API 限流 | Futu OpenD 有频率限制，批量拉取时每个请求间隔 1 秒 |

---

## 实现现状核对表

> 核对基准：`market_scorer.py` / `config.py` / `storage.py` / `allocation.py` / `api_server.py` / `cli.py`，核对日期 2026-10-12。

| 文档章节 | 策略要素 | 代码现状 | 对应代码位置 |
|---------|---------|---------|-------------|
| 3.1 / 5.1 | 三维度权重 50/35/15 | 已实现 ✅ | `config.py:196-200`；`market_scorer.py:258-262` |
| 3.1 / 4.3 / 4.5 / 4.6 | 波动率/量能/避险维度 | 未实现 ❌（已移除） | `market_scorer.py:231-232,354-357` |
| 4.1.1 / 4.2.1 | RSI 周期 | 部分实现 ⚠️（用 RSI6，非 RSI14） | `market_scorer.py:81,123`；`config.py:120,130` |
| 4.1.1 | RSI 评分映射 | 部分实现 ⚠️（分档 `int(rsi/10)*10`，非线性） | `market_scorer.py:82,124` |
| 4.1.2 | 日线 MACD 百分位 (252) | 已实现 ✅ | `market_scorer.py:88-91` |
| 4.1.3 | 日线布林 %B | 已实现 ✅ | `market_scorer.py:96-100` |
| 4.2.2 | 周线 MACD 百分位 (52) | 已实现 ✅ | `market_scorer.py:130-133` |
| 4.2.3 | 周线布林 %B | 已实现 ✅（文档原写「不加布林带」，已更正） | `market_scorer.py:137-145` |
| 4.4.1 | 52 周位置 (252 根 high/low) | 已实现 ✅ | `market_scorer.py:166-176` |
| 4.4.2 | ATH 回撤（零分线 15%） | 已实现 ✅（文档原 20%，已更正） | `market_scorer.py:180-182` |
| 4.4.3 | MA200 偏离（±15%） | 已实现 ✅（文档原 ±20%，已更正） | `market_scorer.py:187-196` |
| 4.7 | 单资产温度（GLD/BTC 独立标定） | 已实现 ✅（文档原先缺失，已补） | `market_scorer.py:397-576` |
| 5.1 | 综合评分公式 | 已实现 ✅ | `market_scorer.py:258-262` |
| 5.2 | 三段仓位映射 | 已实现 ✅ | `market_scorer.py:279-287` |
| 5.2 | 映射区间表（65~100 档） | 部分实现 ⚠️（原数值旧映射遗留，已重算） | `market_scorer.py:285-287` |
| 5.3 | 极端层触发条件（composite≤15 + 日/周 RSI<30） | 已实现 ✅ | `market_scorer.py:269-276` |
| 5.3 | `leverage_tool` 分级 (margin / margin+OTM_call) | 已实现 ✅ | `market_scorer.py:290-294` |
| 5.3 / C.2 | `extreme_triggered` 字段 | 已实现 ✅ | `market_scorer.py:344`；`storage.py:74` |
| — | `extreme_level` 字段 (none/light/heavy) | 已实现 ✅（文档原先缺失，未落库仅内存返回） | `market_scorer.py:297,345` |
| 5.4 / 5.5 | 底部确认辅助信号 / 杠杆区执行规则 | 未实现 ❌（人工规则） | 未找到 |
| 6.1~6.3 | 评估节奏 / 调仓幅度 / 冷却期 | 未实现 ❌（人工规则） | 未找到 |
| 6.4 | 仓位硬限制 | 部分实现 ⚠️（映射下限 30%/上限 85%，其余为人工规则） | `market_scorer.py:287` |
| 7.1 | 数据缺失 → 中性 50 | 已实现 ✅ | `market_scorer.py:210-219` |
| 7.2 / 7.3 | 极端加速 / GLD 同向异常 | 未实现 ❌ | 未找到 |
| 8.1~8.7 | 指标计算参考代码 | 未实现 ❌（仅为 v1.0 示例，非运行代码） | 实际见 `market_scorer.py` / `indicators.py` |
| 9.1~9.3 | 历史场景回测示例 | 部分实现 ⚠️（示例基于旧四维口径，非当前算法） | 见第 9 节说明 |
| 10 | 操作记录模板权重表 | 已实现 ✅（已更正为三维度） | — |
| 11 | 参数调优表 | 部分实现 ⚠️（权重/RSI/ATH/MA200 已更正；VIX/量比行标注未实现） | — |
| C.2 | `market_score` 表结构 | 已实现 ✅ | `storage.py:69-102` |
| C.3 | `/api/market-temperature` | 部分实现 ⚠️（返回库表行 + `gld_temp`/`btc_temp`；`dimensions`/`indicators` 由前端决定） | `api_server.py:438-446` |
| C.3 | `/api/market-temperature/history` | 已实现 ✅ | `api_server.py:449-455` |
| C.3 | `/api/asset-temperature/history` | 已实现 ✅（文档原先缺失） | `api_server.py:458-466` |
| C.4.1 | 市场温度状态文案映射 | 已实现 ✅（与代码逐字一致） | `market_scorer.py:23-32` |
| C.4.2 | 杠杆工具文案映射 | 已实现 ✅ | `market_scorer.py:290-294` |
| C.5 | APScheduler 定时任务 | 未实现 ❌（实为 `daily_sync.bat`） | `scripts/daily_sync.bat` |
| — | `trader-analysis temperature` 命令 | 已实现 ✅ | `cli.py:326-356` |
| — | 加仓建议分级 strong_buy/buy/watch/expensive | 已实现 ✅（配置仓位组合，非市场温度） | `allocation.py:112-179` |
| — | 目标仓位与实际偏离 + 分批加仓计划 | 已实现 ✅（黄金/比特币现货区间） | `allocation.py:247-358` |

**结论统计**：共 38 项 —— 已实现 ✅ 25 项 / 部分实现 ⚠️ 7 项 / 未实现 ❌ 6 项。

> 说明：`allocation.py` 的「目标仓位 vs 实际偏离 / 加仓建议分级 / 分批加仓」属于**永久投资组合配置**模块，与本文档的「市场温度→权益仓位」是两套独立体系，此处仅作关联登记。
