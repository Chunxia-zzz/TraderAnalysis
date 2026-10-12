# 基本面分析模块技术方案

> 版本：v1.0
> 日期：2026-05-07
> 状态：主体已实现（数据获取 / 存储 / 评分三层已落地）；API 端点等以实际代码为准

---

## 1. 目标

为 TraderAnalysis 系统新增**基本面评估**能力，与现有技术面评分（`scorer.py`）形成互补。

- 数据源（**辅助**）：yfinance（免费、无需 API Key）。⚠️ 仅为辅助源，在中国大陆可能无法访问，`forward_pe` 等字段大量缺失（见 `cli.py:226-228` 的显式警告）。
- 数据源（**估值主源**）：**晨星公允价值 + 分析师目标价**，由富途脚本写入 `watchlist` 表（见 1.1）。
- yfinance 路径不依赖 Futu OpenD，可离线运行；富途估值源需要 OpenD。
- 架构风格对齐现有三层设计（数据获取 → 存储 → API 暴露）
- 计算完成后同步关键指标到 `watchlist` 表（详见第 17 节）

### 1.1 真实估值数据源

`fundamental` 命令走 yfinance，但其拉取质量不可靠（尤其大陆网络环境），**不应作为估值判断的主依据**。实际用于估值的数据来自以下两个富途脚本：

| 脚本 | 行为 | 写入字段 |
|------|------|---------|
| `scripts/fetch_fundamental_targets.py` | 遍历 `watchlist` 表标的（排除 ETF/ETN），调用富途 API（`get_research_analyst_consensus.py`、`get_research_morningstar_report.py`）拉取分析师平均目标价与晨星公允价值并写回 DB；支持 `--dry-run` 预览 | `watchlist.analyst_target_mean`、`watchlist.morningstar_fair_value` |
| `scripts/audit_morningstar.py` | 核对 DB 中 `morningstar_fair_value` 与富途 API 实时值的偏差（>1% 标记）；支持 `--all` 全量、`--fix` 将 API 实时值回写 | 核对 / 回写 `watchlist.morningstar_fair_value` |

> 因此，估值折价应以**晨星公允价值 + 分析师目标价**为准，而非 yfinance 的 `forward_pe` 等字段。

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
| `api_server.py` | 新增 1 个 API 端点 |
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
    recommendation     TEXT,                -- strong_buy / buy / hold / underperform / sell / strong_sell

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

从 yfinance 拉取标的池（`watchlist` 表，默认排除已退出标的）中所有标的的基本面数据，写入 `fundamental_data` 表。
（yfinance 仅作辅助源，不可靠，见 1.1。）

### 5.2 代码映射

入参为 **Futu 格式代码字符串**（如 `US.AAPL`、`HK.07709`），转为 yfinance symbol：

| Futu code 输入 | yfinance symbol | 说明 |
|---------------|-----------------|------|
| `US.AAPL` | `AAPL` | 美股直接用 ticker |
| `HK.07709` | `7709.HK` | 港股去前导零 + `.HK` |

```python
def to_yfinance_symbol(code: str) -> str:
    """将 Futu 格式代码转为 yfinance symbol。

    US.AAPL → AAPL
    HK.07709 → 7709.HK
    """
    parts = code.split(".", 1)
    if len(parts) != 2:
        return code
    market, ticker = parts
    if market == "US":
        return ticker
    elif market == "HK":
        # 港股: 去前导零 + .HK
        return f"{int(ticker)}.HK" if ticker.isdigit() else f"{ticker}.HK"
    return ticker
```

### 5.3 拉取策略

```python
def fetch_all(code_list: list[str]) -> list[dict]:
    """
    批量拉取基本面数据。

    策略：
    - 逐只调用 fetch_single(code)（内部 yf.Ticker(symbol).info）
    - 命中 FUNDAMENTAL_SKIP_TICKERS 的标的直接跳过
    - 每只之间 sleep FUNDAMENTAL_FETCH_INTERVAL（= 2.0s），避免 Yahoo 限频
    - 失败的标的跳过并记录 warning

    返回：[{"code": "US.SNDK", "data": {...}}, ...]，跳过/失败的不在列表中
    """

def fetch_single(code: str) -> dict | None:
    """单只拉取。最多尝试 2 次：仅在限频（含 'Rate'）时暂停 30s 后重试 1 次，
    其余异常直接返回 None。"""
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

`FUNDAMENTAL_SKIP_TICKERS`（`config.py:216`，共 8 项）中的标的直接跳过拉取：

```python
FUNDAMENTAL_SKIP_TICKERS = ["QQQ", "SPY", "GLD", "IBIT", "07709", "VIXY", "VIX", "DRAM"]
```

匹配方式为「ticker 后缀」判断（`fetch_single` / `fetch_all` 取 `code.split(".")[-1]` 与列表比对），因此 `US.QQQ`、`HK.07709` 等均能命中。这些标的（ETF / 杠杆产品 / 波动率指数）：
- 没有 EPS / PE / 分析师目标价
- `info` 字典缺少大部分基本面字段

**处理策略**：命中黑名单的标的跳过拉取，不写入 `fundamental_data`、不参与评分；未列入黑名单但字段缺失的标的，缺失字段填 `None`，评分时该维度得 0 分，**不做权重归一化**（详见 6.4）。

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
def _score_valuation_discount(current_price: float | None, target_mean: float | None) -> dict:
    """
    目标价上行空间映射。
    upside = (target_mean - current_price) / current_price
    - upside >= 30% → ratio = 1.0（满分）
    - upside <= -10% → ratio = 0.0（零分）
    - 线性插值；current_price / target_mean 缺失时返回 ratio = None
    """
    upside = (target_mean - current_price) / current_price
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
    recommendation 映射（6 个取值）:
      strong_buy   → 1.0
      buy          → 0.75
      hold         → 0.4
      underperform → 0.2
      sell         → 0.1
      strong_sell  → 0.0
      （未知/缺失 → 默认 0.4）
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

当某维度所需字段全部为 None 时（如 ETF 无 PE/EPS），该维度返回：

```python
{"score": 0.0, "raw": None, "ratio": None}     # 多数维度
{"score": 0.0, "raw": forward_pe, "ratio": None}  # pe_reasonability 例外：保留 raw 便于排查
```

**实际实现（`fundamental_scorer.py`）**：
- 该维度得分 = 0，`ratio = None`
- **不做权重归一化**，总分 = 5 个维度得分直接相加（`total = f1+f2+f3+f4+f5`）
- breakdown **不含 `"skipped"` 字段**；前端可通过 `ratio === null` 判断并展示"不适用"

选此策略的理由：
- 逻辑简单透明
- ETF 本身不适合基本面评分，低分符合语义（"不适合用基本面衡量"）
- 缺失信息可通过 `ratio: null` 无损区分于"真实得 0 分"

---

## 7. 存储层改动 — `storage.py`

### 7.1 新增函数

```python
def upsert_fundamental(code: str, date: str, data: dict) -> None:
    """插入或更新 fundamental_data 记录。"""

def query_latest_fundamental(code: str) -> dict | None:
    """查询某标的最新基本面数据。"""

def query_fundamentals_overview() -> list[dict]:
    """查询所有标的最新基本面评分，按分数降序。
    （已实现，但尚未接入 API —— 全仓无调用点）"""
```

> 注：`query_fundamental_by_date(code, date)` 在代码中**不存在**，故不列出。

---

## 8. API 端点 — `api_server.py`

> ⚠️ 本模块**仅有一个** API 端点：`GET /api/fundamental`（`api_server.py:1709`）。
> 文档早期版本提到的 `/api/fundamental/latest`、`/api/fundamental/overview` **均不存在**；
> `breakdown`、`valuation_signal` 以及 `valuation{}`/`growth{}`/`analyst{}`/`financial_health{}` 分块结构**也不在响应中**。

### 8.1 `GET /api/fundamental`

返回某标的的估值概览（分析师目标价 + 晨星公允价值 + 部分基本面字段），**扁平结构**。

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | string | 是 | 标的代码 (US.SNDK) |
| `date` | string | 否 | 指定日期 YYYY-MM-DD，按该日期取收盘价；不传取最新 |

**响应 200**

```json
{
  "code": "US.TMUS",
  "current_price": 148.58,
  "analyst_target": 210.0,
  "analyst_upside_pct": 41.3,
  "morningstar_value": 235.0,
  "morningstar_discount_pct": 58.2,
  "forward_pe": 12.4,
  "peg_ratio": 0.8,
  "roe": 15.2,
  "market_cap": 172000000000.0
}
```

**无数据时**（`code` 不在 `watchlist` 表）：

```json
{"data": null, "message": "US.SNDK 暂无基本面数据"}
```

**无价格时**（DB 无收盘价且 `watchlist.current_price` 也为空）：

```json
{"data": null, "message": "US.SNDK 暂无价格数据"}
```

**字段口径**

- `analyst_upside_pct = (analyst_target − current_price) / current_price × 100`，即「分析师目标价上行空间%」。
- `morningstar_discount_pct = (morningstar_value − current_price) / current_price × 100`，即「**上涨空间%**」，**不是折价率**（详见第 18 节口径声明）。
- `forward_pe` / `peg_ratio` / `roe` / `market_cap` 取自 `watchlist` 表的同步字段（未同步时为 `null`）。

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
FUNDAMENTAL_FETCH_INTERVAL: float = 2.0

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

# 跳过拉取的标的（ETF、杠杆产品、波动率指数等无法做基本面分析；按 ticker 后缀匹配）
FUNDAMENTAL_SKIP_TICKERS: list[str] = ["QQQ", "SPY", "GLD", "IBIT", "07709", "VIXY", "VIX", "DRAM"]
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
| yfinance 某只标的无数据/404 | 跳过，打印 warning，不影响其他标的 |
| 拉取异常 | 立即放弃该标的（`fetch_single` 最多尝试 2 次）；仅限频（`Rate`）时暂停 30s 重试 1 次 |
| Yahoo 限频 (429) | 暂停 30s 后重试 1 次，仍失败则跳过该标的 |
| 字段返回 None | 存 NULL，评分时该维度得 0 分 |
| ETF / 杠杆产品 | 命中 `FUNDAMENTAL_SKIP_TICKERS`（8 项）直接跳过 |
| yfinance 在大陆不可访问 | 该源整体不可用时 `forward_pe` / `target_mean` 等大量缺失、对应维度得 0；估值请以晨星公允价值 + 分析师目标价为准（见 1.1） |

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

> 注：原列于本节的「港股支持」**已在 v1 实现** —— `fundamental_fetcher.py:49-64` 的 `to_yfinance_symbol` 已支持 HK → `{int(ticker)}.HK` 映射（去前导零，如 `HK.07709` → `7709.HK`）。

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

基本面模块拉取数据后，将以下字段同步到 `watchlist` 表对应标的（实现内联在 `cli.py:261-281`）：

| fundamental_data 字段 | → watchlist 表字段 | 写入方式 |
|----------------------|-------------------|---------|
| `forward_pe` | `forward_pe` | 可编辑字段（`update_stock`） |
| `forward_eps` | `forward_eps` | 可编辑字段 |
| `peg_ratio` | `peg_ratio` | 可编辑字段 |
| `revenue_growth` | `revenue_growth` | 可编辑字段 |
| `earnings_growth` | `earnings_growth` | 可编辑字段 |
| `profit_margin` | `profit_margin` | 可编辑字段 |
| `roe` | `roe` | 可编辑字段 |
| `debt_to_equity` | `debt_to_equity` | 可编辑字段 |
| `trailing_pe` | `trailing_pe` | 快照字段（`refresh_snapshot`，不可编辑） |
| `market_cap` | `market_cap` | 快照字段 |
| `current_price` | `current_price` | 快照字段 |
| `dividend_yield` | `dividend_yield` | 快照字段 |
| `beta` | `beta` | 快照字段 |

> ⚠️ `analyst_target_mean` **不在**上述同步列表内。它由 `scripts/fetch_fundamental_targets.py`（富途 API）直接写入 `watchlist` 表，与 yfinance 拉取无关。
> `morningstar_fair_value` 则是「**可编辑 + 由富途脚本自动刷新**」：它同时出现在 `watchlist_storage.py:64` 的 `EDITABLE_FIELDS`（可经 `PATCH /api/watchlist/{code}` 手动修改），又会被 `fetch_fundamental_targets.py:123-141` 自动写库、被 `audit_morningstar.py:71-79`（`--fix`）回写刷新。

### 17.2 同步实现

代码中**没有**独立的 `sync_fundamental_to_watchlist()` 函数；同步逻辑内联在 `fundamental` 命令中（`cli.py:261-281`）：

```python
# cli.py — fundamental 命令内，对每只成功标的执行

# 1) 可编辑字段：仅在取值非 None 时写入
sync_fields = {}
for src, dst in [
    ("forward_pe", "forward_pe"), ("forward_eps", "forward_eps"),
    ("peg_ratio", "peg_ratio"), ("revenue_growth", "revenue_growth"),
    ("earnings_growth", "earnings_growth"), ("profit_margin", "profit_margin"),
    ("roe", "roe"), ("debt_to_equity", "debt_to_equity"),
]:
    if data.get(src) is not None:
        sync_fields[dst] = data[src]
if sync_fields:
    update_stock(code, sync_fields)

# 2) 快照字段：同样仅在取值非 None 时写入
snapshot = {}
for f in ["trailing_pe", "market_cap", "current_price", "dividend_yield", "beta"]:
    if data.get(f) is not None:
        snapshot[f] = data[f]
if snapshot:
    refresh_snapshot(code, snapshot)
```

规则：
- 可编辑字段与快照字段均为「最新数据覆盖」，但**仅写非 None 值**（不会用空值清空已有数据）。
- `morningstar_fair_value`、`thesis`、`notes` 等不在本同步列表内：前者由富途脚本维护，后两者为用户手动字段。

### 17.3 用户手动覆盖

用户通过 `PATCH /api/watchlist/{code}` 手动修改的 `forward_pe` 等字段，
下次 `trader-analysis fundamental` 执行时会被 yfinance 最新数据覆盖。

如果用户想保留自己的估算值不被覆盖，可选方案：
- **v1（当前）：** 不做保护，每次 fundamental 执行统一覆盖。用户清楚这个行为即可。
- **v2（未来）：** 加 `user_override` 标记，被用户手动改过的字段不再自动覆盖。

---

## 18. 口径声明：晨星折价 vs 分析师上行空间

⚠️ 本模块存在**两套容易混淆的「上行空间」口径**，务必区分。

### 18.1 `ms_discount_pct` / `morningstar_discount_pct` = 上涨空间（不是折价率）

字段名里虽带 "discount"，但计算口径是：

```
ms_discount_pct = (晨星公允价值 − 现价) / 现价 × 100
```

即**「相对现价的上涨空间%」**，**不是「折价率」**。见 `api_server.py:389`（`ms_discount_pct`）、`api_server.py:1755`（`morningstar_discount_pct`）、`allocation.py:173`（加仓建议里的「低估 X%」为同一口径）。

**示例**：TMUS 现价 148.58、晨星公允价值 235 → 显示 `58.2`，含义是「现价相对晨星公允价值**还有约 58% 上行空间**」，而非「打了 58% 折扣」。
是否低估的直接判据是 `ms_undervalued = 现价 < 晨星公允价值`（`api_server.py:390`）。

### 18.2 F1 因子用的是「分析师目标价上行空间」

第 6 节 F1 因子（估值折价）用的是：

```
upside = (target_mean − current_price) / current_price   # 分析师目标价上行空间
```

该口径**基于分析师一致预期目标价（`target_mean`）**，与 18.1 的晨星公允价值口径是**两套完全独立的数据**，不可混用：

- 晨星口径 → `watchlist.morningstar_fair_value`（富途脚本写入，用于第 8 节 API 的 `morningstar_discount_pct`）。
- 分析师口径 → `watchlist.analyst_target_mean`（富途脚本写入，第 8 节 API 的 `analyst_upside_pct`）。

> 注：F1 计算读取的 `target_mean` 来自 yfinance 字段映射（`fundamental_fetcher._FIELD_MAP` 中的 `targetMeanPrice`），yfinance 不可用时该值缺失、F1 得 0 分；它与富途写入的 `analyst_target_mean` 是两个不同字段，后者目前**未接入** F1 计算。
