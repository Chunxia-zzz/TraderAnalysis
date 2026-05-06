# 基本面分析模块技术方案

> 版本：v1.0
> 日期：2026-05-07
> 状态：已实现

---

## 1. 目标

为 TraderAnalysis 系统新增**基本面评估**能力，与现有技术面评分（`scorer.py`）形成互补。

- 数据源：yfinance（免费、无需 API Key、覆盖美股/港股）
- 不依赖 Futu OpenD（可完全离线运行）
- 架构风格对齐现有三层设计（数据获取 → 存储 → API 暴露）
- 计算完成后同步关键指标到 `watchlist` 表（详见第 17 节）

---

## 2. 架构对照

```
层级           现有（技术面）                 新增（基本面）
──────────     ────────────────────         ─────────────────────────
数据获取       data_fetcher.py (Futu)       fundamental_fetcher.py (yfinance)
计算           indicators.py + scorer.py    fundamental_scorer.py
存储           storage.py (SQLite)          storage.py 新增表
API            api_server.py                api_server.py 新增端点
CLI            cli.py (score 命令)          cli.py (fundamental 命令)
```

---

## 3. 文件清单

### 3.1 新增文件

| 路径 | 职责 |
|------|------|
| `src/trader_analysis/futu_strategy/fundamental_fetcher.py` | yfinance 数据批量采集 |
| `src/trader_analysis/futu_strategy/fundamental_scorer.py` | 基本面多因子评分引擎 |

### 3.2 修改文件

| 路径 | 改动点 |
|------|--------|
| `config.py` | 新增 `FUNDAMENTAL_*` 配置常量 |
| `storage.py` | 新增 `fundamental_data` 表 DDL + CRUD 函数 |
| `api_server.py` | 新增 2 个 API 端点 |
| `cli.py` | 新增 `fundamental` 命令 |
| `pyproject.toml` | dependencies 新增 `yfinance>=0.2.36` |

---

## 4. 数据模型

### 4.1 SQLite 表结构 — `fundamental_data`

```sql
CREATE TABLE IF NOT EXISTS fundamental_data (
    code               TEXT NOT NULL,       -- Futu 格式代码 (US.SNDK)
    date               TEXT NOT NULL,       -- 数据日期 YYYY-MM-DD
    current_price      REAL,                -- 当前股价

    -- 估值指标
    trailing_pe        REAL,                -- 滚动 PE
    forward_pe         REAL,                -- 前瞻 PE
    trailing_eps       REAL,                -- 滚动 EPS
    forward_eps        REAL,                -- 前瞻 EPS (分析师一致预期)
    peg_ratio          REAL,                -- PEG = PE / 盈利增速
    price_to_book      REAL,                -- 市净率
    ev_to_ebitda       REAL,                -- EV/EBITDA

    -- 成长性
    revenue_growth     REAL,                -- 营收增速 (YoY)
    earnings_growth    REAL,                -- 盈利增速 (YoY)
    revenue_per_share  REAL,                -- 每股营收

    -- 分析师数据
    target_mean        REAL,                -- 目标价均值
    target_median      REAL,                -- 目标价中位数
    target_high        REAL,                -- 目标价最高
    target_low         REAL,                -- 目标价最低
    analyst_count      INTEGER,             -- 覆盖分析师数量
    recommendation     TEXT,                -- buy / hold / sell / strong_buy

    -- 财务健康
    current_ratio      REAL,                -- 流动比率
    debt_to_equity     REAL,                -- 资产负债率
    free_cashflow      REAL,                -- 自由现金流
    operating_cashflow REAL,                -- 经营现金流
    profit_margin      REAL,                -- 净利润率
    gross_margin       REAL,                -- 毛利率
    roe                REAL,                -- 净资产收益率 (Return on Equity)

    -- 其他
    market_cap         REAL,                -- 总市值
    dividend_yield     REAL,                -- 股息率
    beta               REAL,                -- Beta 系数
    short_ratio        REAL,                -- 做空比率

    -- 评分结果
    fundamental_score  REAL,                -- 综合评分 0~100
    valuation_signal   TEXT,                -- UNDERVALUED / FAIR / OVERVALUED
    breakdown          TEXT,                -- JSON 格式的各维度得分明细

    updated_at         TEXT,                -- 更新时间
    PRIMARY KEY (code, date)
);

CREATE INDEX IF NOT EXISTS idx_fundamental_code_date
    ON fundamental_data(code, date);
```

### 4.2 与现有表的关系

```
watchlist 表 (SQLite, 标的池管理)
    ↓ 提供标的列表
kline_indicators ←── 技术面数据 (Futu OpenD)
score_results    ←── 技术面评分 (scorer.py)
market_score     ←── 市场温度 (market_scorer.py)
fundamental_data ←── 基本面数据+评分 (yfinance) [新增]
    ↓ 同步 forward_pe/eps 等回写
watchlist 表     ←── 更新可编辑基本面字段
```

> 注：标的列表来源已从 `watchlist.json` 迁移到 SQLite `watchlist` 表，
> 详见 `watchlist-management-design.md`。

---

## 5. 数据获取层 — `fundamental_fetcher.py`

### 5.1 核心职责

从 yfinance 拉取 `watchlist.json` 中所有标的的基本面数据，写入 `fundamental_data` 表。

### 5.2 代码映射

watchlist.json 中的 ticker 到 yfinance symbol 的映射规则：

| watchlist 格式 | yfinance symbol | 说明 |
|---------------|-----------------|------|
| `{"ticker": "SNDK", "market": "US"}` | `SNDK` | 美股直接用 ticker |
| `{"ticker": "07709", "market": "HK"}` | `7709.HK` | 港股用 `{number}.HK` |

```python
def to_yfinance_symbol(item: dict) -> str:
    """将 watchlist 条目转为 yfinance 格式。"""
    ticker = item["ticker"]
    market = item["market"]
    if market == "US":
        return ticker
    elif market == "HK":
        # 港股: 去掉前导零 + .HK
        return f"{int(ticker)}.HK" if ticker.isdigit() else f"{ticker}.HK"
    else:
        return ticker  # fallback
```

### 5.3 拉取策略

```python
def fetch_fundamentals(code_list: list[str]) -> list[dict]:
    """
    批量拉取基本面数据。

    限频策略：
    - 逐个调用 yf.Ticker(symbol).info（~0.7s/只）
    - 每只之间 sleep 0.5s，避免 Yahoo 限频
    - 40只总耗时约 40~50s
    - 失败的标的跳过并记录 warning

    返回：[{"code": "US.SNDK", "data": {...}}, ...]
    """
```

### 5.4 字段提取映射

| 目标字段 | yfinance info key | 备注 |
|---------|-------------------|------|
| `current_price` | `currentPrice` 或 `regularMarketPrice` | |
| `trailing_pe` | `trailingPE` | |
| `forward_pe` | `forwardPE` | |
| `trailing_eps` | `trailingEps` | |
| `forward_eps` | `forwardEps` | 分析师一致预期 |
| `peg_ratio` | `pegRatio` | |
| `price_to_book` | `priceToBook` | |
| `ev_to_ebitda` | `enterpriseToEbitda` | |
| `revenue_growth` | `revenueGrowth` | 小数形式 (0.25 = 25%) |
| `earnings_growth` | `earningsGrowth` | |
| `revenue_per_share` | `revenuePerShare` | |
| `target_mean` | `targetMeanPrice` | |
| `target_median` | `targetMedianPrice` | |
| `target_high` | `targetHighPrice` | |
| `target_low` | `targetLowPrice` | |
| `analyst_count` | `numberOfAnalystOpinions` | |
| `recommendation` | `recommendationKey` | |
| `current_ratio` | `currentRatio` | |
| `debt_to_equity` | `debtToEquity` | |
| `free_cashflow` | `freeCashflow` | |
| `operating_cashflow` | `operatingCashflow` | |
| `profit_margin` | `profitMargins` | |
| `gross_margin` | `grossMargins` | |
| `roe` | `returnOnEquity` | |
| `market_cap` | `marketCap` | |
| `dividend_yield` | `dividendYield` | |
| `beta` | `beta` | |
| `short_ratio` | `shortRatio` | |

### 5.5 ETF / 特殊标的处理

watchlist 中包含 ETF（QQQ、SPY、GLD、IBIT）和港股杠杆产品（07709），这些标的：
- 没有 EPS / PE / 分析师目标价
- `info` 字典缺少大部分基本面字段

**处理策略**：缺失字段填 `None`，评分时跳过无法计算的维度（按剩余维度重新归一化权重）。

---

## 6. 评分引擎 — `fundamental_scorer.py`

### 6.1 评分维度（5 因子，满分 100）

| # | 维度 | 权重 | 输入字段 | 评分逻辑 |
|---|------|------|---------|---------|
| F1 | 估值折价 | 30 | `current_price`, `target_mean` | 目标价上行空间越大，得分越高 |
| F2 | PE 合理性 | 20 | `forward_pe` | Forward PE 越低（相对行业），得分越高 |
| F3 | 成长性 | 20 | `revenue_growth`, `earnings_growth` | 双增长越强，得分越高 |
| F4 | 财务健康 | 15 | `roe`, `profit_margin`, `debt_to_equity` | ROE高+利润率高+低负债 |
| F5 | 分析师共识 | 15 | `recommendation`, `analyst_count` | 强烈买入+覆盖多=高分 |

### 6.2 各维度评分公式

#### F1: 估值折价（权重 30）

```python
def _score_valuation_discount(price: float, target_mean: float) -> dict:
    """
    目标价上行空间映射。
    upside = (target_mean - price) / price
    - upside >= 30% → ratio = 1.0（满分）
    - upside <= -10% → ratio = 0.0（零分）
    - 线性插值
    """
    upside = (target_mean - price) / price
    ratio = clamp((upside + 0.10) / 0.40)  # -10%→0, +30%→1
    return {"score": ratio * 30, "raw": upside, "ratio": ratio}
```

#### F2: PE 合理性（权重 20）

```python
def _score_pe_reasonability(forward_pe: float) -> dict:
    """
    Forward PE 连续映射（通用标准，不区分行业）。
    - PE <= 10 → ratio = 1.0（极度便宜）
    - PE >= 40 → ratio = 0.0（太贵）
    - 线性插值
    注：PE 为负（亏损公司）时 ratio = 0
    """
    if forward_pe is None or forward_pe <= 0:
        return {"score": 0.0, "raw": forward_pe, "ratio": 0.0}
    ratio = clamp((40 - forward_pe) / 30)  # 10→1, 40→0
    return {"score": ratio * 20, "raw": forward_pe, "ratio": ratio}
```

#### F3: 成长性（权重 20）

```python
def _score_growth(revenue_growth: float, earnings_growth: float) -> dict:
    """
    综合增长率评分。
    combined = 0.5 * revenue_growth + 0.5 * earnings_growth
    - combined >= 30% → ratio = 1.0
    - combined <= 0%  → ratio = 0.0
    - 线性插值
    """
    rev_g = revenue_growth or 0
    earn_g = earnings_growth or 0
    combined = 0.5 * rev_g + 0.5 * earn_g
    ratio = clamp(combined / 0.30)  # 0%→0, 30%→1
    return {"score": ratio * 20, "raw": combined, "ratio": ratio}
```

#### F4: 财务健康（权重 15）

```python
def _score_financial_health(roe: float, profit_margin: float, debt_to_equity: float) -> dict:
    """
    三项子指标取平均。
    - ROE: >=20% → 1.0, <=0% → 0.0
    - Profit Margin: >=25% → 1.0, <=0% → 0.0
    - Debt/Equity (反向): <=50 → 1.0, >=200 → 0.0
    """
    roe_ratio = clamp((roe or 0) / 0.20)
    pm_ratio = clamp((profit_margin or 0) / 0.25)
    de_ratio = clamp((200 - (debt_to_equity or 100)) / 150)  # 低负债=高分

    avg_ratio = (roe_ratio + pm_ratio + de_ratio) / 3
    return {"score": avg_ratio * 15, "raw": {"roe": roe, "pm": profit_margin, "de": debt_to_equity}, "ratio": avg_ratio}
```

#### F5: 分析师共识（权重 15）

```python
def _score_analyst_consensus(recommendation: str, analyst_count: int) -> dict:
    """
    推荐等级 + 覆盖人数综合。
    recommendation 映射:
      strong_buy → 1.0
      buy        → 0.75
      hold       → 0.4
      sell       → 0.1
      strong_sell→ 0.0
    覆盖系数:
      count >= 15 → 1.0（充分覆盖）
      count < 3   → 0.5（覆盖不足，打折）
      线性插值
    最终 ratio = rec_score * coverage_factor
    """
    REC_MAP = {"strong_buy": 1.0, "buy": 0.75, "hold": 0.4,
               "underperform": 0.2, "sell": 0.1, "strong_sell": 0.0}
    rec_score = REC_MAP.get(recommendation, 0.4)
    coverage = clamp((analyst_count - 3) / 12) * 0.5 + 0.5  # 3→0.5, 15→1.0
    ratio = rec_score * coverage
    return {"score": ratio * 15, "raw": recommendation, "ratio": ratio}
```

### 6.3 汇总与信号

```python
def calculate_fundamental_score(code: str, data: dict) -> dict:
    """
    汇总 5 个维度，返回评分结果。

    Returns:
    {
        "code": "US.SNDK",
        "fundamental_score": 72.5,
        "valuation_signal": "UNDERVALUED",
        "breakdown": {
            "valuation_discount": {"score": 22.5, "raw": 0.18, "ratio": 0.75},
            "pe_reasonability":   {"score": 15.0, "raw": 8.4,  "ratio": 0.75},
            "growth":             {"score": 18.0, "raw": 0.27, "ratio": 0.90},
            "financial_health":   {"score": 9.0,  "raw": {...}, "ratio": 0.60},
            "analyst_consensus":  {"score": 8.0,  "raw": "buy", "ratio": 0.53}
        }
    }
    """
```

**信号映射**：

| 区间 | signal | 含义 | 前端颜色建议 |
|------|--------|------|-------------|
| >= 75 | `UNDERVALUED` | 基本面优秀且低估 | 绿色 `#2e7d32` |
| 40 ~ 75 | `FAIR` | 估值合理 | 灰色 `#757575` |
| < 40 | `OVERVALUED` | 偏贵或基本面弱 | 红色 `#c62828` |

### 6.4 缺失数据处理

当某维度所需字段全部为 None 时（如 ETF 无 PE/EPS）：
1. 该维度得分 = 0，ratio = None
2. 剩余维度按原权重比例重新归一化（可选，或直接按 0 处理，在 breakdown 中标注 `"skipped": true`）

推荐策略：**不做归一化，缺失维度直接 0 分**。理由：
- 逻辑简单透明
- ETF 本身不适合基本面评分，低分符合语义（"不适合用基本面衡量"）
- 前端可通过 breakdown 中 `ratio: null` 判断并展示"不适用"

---

## 7. 存储层改动 — `storage.py`

### 7.1 新增函数

```python
def upsert_fundamental(code: str, date: str, data: dict) -> None:
    """插入或更新 fundamental_data 记录。"""

def query_latest_fundamental(code: str) -> dict | None:
    """查询某标的最新基本面数据。"""

def query_fundamental_by_date(code: str, date: str) -> dict | None:
    """查询某标的指定日期的基本面数据。"""

def query_fundamentals_overview() -> list[dict]:
    """查询所有标的最新基本面评分，按分数降序。"""
```

---

## 8. API 端点 — `api_server.py`

### 8.1 `GET /api/fundamental/latest`

返回某标的最新基本面分析数据。

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | string | 是 | 标的代码 (US.SNDK) |

**响应 200**

```json
{
  "code": "US.SNDK",
  "date": "2026-05-06",
  "current_price": 1406.32,
  "valuation": {
    "trailing_pe": 48.08,
    "forward_pe": 8.37,
    "trailing_eps": 29.25,
    "forward_eps": 168.00,
    "peg_ratio": 0.12,
    "price_to_book": 5.2,
    "ev_to_ebitda": 15.3
  },
  "growth": {
    "revenue_growth": 2.51,
    "earnings_growth": 1.44
  },
  "analyst": {
    "target_mean": 1347.82,
    "target_median": 1258.50,
    "target_high": 2000.00,
    "target_low": 843.00,
    "analyst_count": 22,
    "recommendation": "buy"
  },
  "financial_health": {
    "roe": 0.18,
    "profit_margin": 0.15,
    "gross_margin": 0.42,
    "debt_to_equity": 85.3,
    "free_cashflow": -120000000,
    "current_ratio": 1.8
  },
  "score": {
    "fundamental_score": 72.5,
    "valuation_signal": "UNDERVALUED",
    "breakdown": {
      "valuation_discount": {"score": 22.5, "raw": 0.18, "ratio": 0.75},
      "pe_reasonability":   {"score": 15.0, "raw": 8.37, "ratio": 0.75},
      "growth":             {"score": 18.0, "raw": 0.27, "ratio": 0.90},
      "financial_health":   {"score": 9.0,  "raw": null, "ratio": 0.60},
      "analyst_consensus":  {"score": 8.0,  "raw": "buy","ratio": 0.53}
    }
  },
  "updated_at": "2026-05-06 04:30:00"
}
```

**无数据时**：`{"data": null, "message": "US.SNDK 暂无基本面数据，请先运行 trader-analysis fundamental"}`

### 8.2 `GET /api/fundamental/overview`

全标的基本面速览，按评分降序。

**响应 200**

```json
{
  "date": "2026-05-06",
  "total_count": 35,
  "undervalued": [
    {"code": "US.SNDK", "fundamental_score": 72.5, "valuation_signal": "UNDERVALUED",
     "forward_pe": 8.37, "target_upside": 0.18, "recommendation": "buy"}
  ],
  "fair": [...],
  "overvalued": [...],
  "skipped": ["US.QQQ", "US.SPY", "US.GLD", "US.IBIT", "HK.07709"],
  "summary": {
    "undervalued_count": 8,
    "fair_count": 22,
    "overvalued_count": 5,
    "skipped_count": 5
  }
}
```

`skipped`：ETF / 杠杆产品等无基本面数据的标的。

---

## 9. CLI 命令 — `cli.py`

```python
@app.command()
def fundamental(
    codes: Optional[list[str]] = typer.Option(None, help="标的代码列表"),
) -> None:
    """拉取基本面数据并评分（数据源：yfinance，不依赖 OpenD）。"""
```

**执行流程**：

```
1. 从 watchlist 表获取活跃标的列表（status != 'exited'）
2. 调用 fundamental_fetcher.fetch_all(code_list)
   → 逐个 yf.Ticker(symbol).info
   → 字段提取 + 异常处理
3. 对每只标的调用 fundamental_scorer.calculate_fundamental_score()
4. 写入 storage.upsert_fundamental()
5. 同步关键字段到 watchlist 表（见第 17 节）
6. 打印摘要（UNDERVALUED 标的高亮）
```

**输出示例**：

```
拉取基本面数据中... (40 只标的)
  US.SNDK ✓  US.MU ✓  US.NVDA ✓  ... (3s/10只)
完成：35 只成功，5 只跳过（ETF/无数据）

── 基本面评分 ──
  UNDERVALUED (8只):
    US.SNDK   72.5分  FPE=8.4x  目标价↑18%  BUY
    US.INTC   71.2分  FPE=12.1x 目标价↑25%  BUY
    ...
  OVERVALUED (5只):
    US.TSLA   35.1分  FPE=95.2x 目标价↓12%  HOLD
    ...
```

---

## 10. 配置项 — `config.py` 新增

```python
# ── 基本面分析 (Fundamental) ─────────────────────────────────────────────────
# yfinance 拉取间隔（秒），防止限频
FUNDAMENTAL_FETCH_INTERVAL: float = 0.5

# 评分权重
FUNDAMENTAL_WEIGHTS: dict[str, int] = {
    "valuation_discount": 30,
    "pe_reasonability": 20,
    "growth": 20,
    "financial_health": 15,
    "analyst_consensus": 15,
}

# 信号阈值
FUNDAMENTAL_SIGNAL_UNDERVALUED: int = 75
FUNDAMENTAL_SIGNAL_OVERVALUED: int = 40

# 跳过评分的标的类型（ETF、杠杆产品等无法做基本面分析）
FUNDAMENTAL_SKIP_TICKERS: list[str] = ["QQQ", "SPY", "GLD", "IBIT", "07709"]
```

---

## 11. 依赖

```toml
# pyproject.toml [project] dependencies 新增：
"yfinance>=0.2.36",
```

安装：
```bash
pip install yfinance>=0.2.36
```

---

## 12. 运行节奏

| 场景 | 频率 | 说明 |
|------|------|------|
| 首次运行 | 手动一次 | `trader-analysis fundamental` |
| 日常更新 | 每日收盘后 | 可加入 cron / docker entrypoint |
| 按需查询 | 随时 | API 端点从 SQLite 读取 |

基本面数据每日更新一次即可（EPS/目标价变化频率为季度级别）。

**建议 cron 排布**（在现有 04:15 更新技术面之后）：

```
# 04:15 技术面更新（已有）
15 4 * * 1-6  trader-analysis update && trader-analysis temperature

# 04:20 基本面更新（新增）
20 4 * * 1-6  trader-analysis fundamental
```

---

## 13. 异常处理

| 场景 | 处理 |
|------|------|
| yfinance 某只标的 404 | 跳过，打印 warning，不影响其他标的 |
| 网络超时 | 重试 1 次（间隔 2s），仍失败则跳过 |
| 字段返回 None | 存 NULL，评分时该维度得 0 分 |
| Yahoo 限频 (429) | 暂停 30s 后继续，或本次中止保留已成功数据 |
| ETF 无基本面数据 | 在 `FUNDAMENTAL_SKIP_TICKERS` 中配置跳过 |

---

## 14. 测试计划

| 测试文件 | 覆盖范围 |
|---------|---------|
| `test_fundamental_scorer.py` | 各维度评分公式、边界值、None 处理 |
| `test_fundamental_fetcher.py` | mock yfinance 返回、字段映射、异常处理 |
| `test_fundamental_api.py` | API 端点响应格式、无数据时返回 |

---

## 15. 后续扩展（不在 v1 范围内）

| 方向 | 说明 |
|------|------|
| 技术面 + 基本面综合评分 | 加权融合两个分数，输出 `combined_score` |
| 行业 PE 对比 | 用 yfinance 的 `sector` 字段按行业分组，计算行业 PE 中位数 |
| 财务报表趋势 | 拉取 `quarterly_financials`，分析营收/利润环比趋势 |
| DCF 自动估值 | 基于 OCF + revenue growth 自动计算 DCF 公允价值 |
| 港股支持 | yfinance 港股代码格式为 `{number}.HK`，需验证覆盖度 |

---

## 16. 实施步骤（建议顺序）

> **前置依赖：** 本模块依赖 `watchlist-management-design.md` 中的 watchlist 表已建好。
> 请先完成标的池迁移后再实施本模块。

1. `pyproject.toml` 加依赖 → `pip install -e .`
2. `config.py` 加配置常量
3. `storage.py` 加表 DDL + CRUD（可先 `init_db()` 建表验证）
4. `fundamental_fetcher.py` 实现数据拉取（先跑单只验证）
5. `fundamental_scorer.py` 实现评分（对照公式逐个写+单测）
6. `cli.py` 加 `fundamental` 命令，端到端跑通
7. `api_server.py` 加端点
8. 实现 watchlist 同步（第 17 节）
9. 补测试
10. 更新 `docs/api.md` 和 `CHANGELOG.md`

---

## 17. 与标的池（watchlist 表）的写入协同

### 17.1 同步目标

基本面模块拉取数据后，将以下字段同步到 `watchlist` 表对应标的的可编辑字段中：

| fundamental_data 字段 | → watchlist 表字段 | 说明 |
|----------------------|-------------------|------|
| `forward_pe` | `forward_pe` | 前瞻市盈率 |
| `forward_eps` | `forward_eps` | 前瞻每股收益 |
| `peg_ratio` | `peg_ratio` | PEG 比率 |
| `revenue_growth` | `revenue_growth` | 营收增长率 |
| `earnings_growth` | `earnings_growth` | 盈利增长率 |
| `profit_margin` | `profit_margin` | 净利润率 |
| `roe` | `roe` | 净资产收益率 |
| `debt_to_equity` | `debt_to_equity` | 资产负债率 |
| `target_mean` | `analyst_target_mean` | 分析师平均目标价 |
| `trailing_pe` | `trailing_pe` | 静态市盈率（不可编辑字段） |
| `market_cap` | `market_cap` | 市值（不可编辑字段） |
| `current_price` | `current_price` | 最近价格（不可编辑字段） |
| `dividend_yield` | `dividend_yield` | 股息率（不可编辑字段） |
| `beta` | `beta` | Beta（不可编辑字段） |

### 17.2 同步函数

```python
def sync_fundamental_to_watchlist(code: str, data: dict) -> None:
    """
    将基本面分析结果同步到 watchlist 表。

    规则：
    - 可编辑字段（forward_pe, roe 等）：无条件写入（最新数据覆盖）
    - 静态快照字段（trailing_pe, market_cap 等）：无条件写入（反映事实）
    - 用户手动字段（morningstar_fair_value, thesis, notes）：不触碰

    调用时机：fundamental 命令执行完毕后，对每只成功拉取的标的执行一次。
    """
```

### 17.3 用户手动覆盖

用户通过 `PATCH /api/watchlist/{code}` 手动修改的 `forward_pe` 等字段，
下次 `trader-analysis fundamental` 执行时会被 yfinance 最新数据覆盖。

如果用户想保留自己的估算值不被覆盖，可选方案：
- **v1（当前）：** 不做保护，每次 fundamental 执行统一覆盖。用户清楚这个行为即可。
- **v2（未来）：** 加 `user_override` 标记，被用户手动改过的字段不再自动覆盖。
