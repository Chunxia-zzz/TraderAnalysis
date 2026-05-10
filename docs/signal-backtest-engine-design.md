# Signal Backtest Engine 技术设计文档

> 最后更新：2026-05-11 | 版本：v2.0 | 状态：P0+P1+扩展 已实现

---

## 1. 概述

### 1.1 目标

基于已有 ~900 天的评分数据（`score_results`）和价格数据（`kline_indicators`），构建一个信号回测引擎，验证"当评分达到阈值时买入，持有 N 个交易日后卖出"的策略收益表现。

### 1.2 核心用例

```
输入: code=US.SNDK, score_threshold=40, holding_period=10
输出: 每次触发信号后持有 10 个交易日的收益率统计
```

### 1.3 设计原则

| 原则 | 说明 |
|------|------|
| 只读 | 不修改现有数据表，回测结果存独立表或仅内存返回 |
| 复用 | 复用现有 storage 层查询函数 |
| 一致 | API/CLI 风格与现有系统保持一致 |
| 渐进 | v1 先做单股单策略，后续扩展批量/组合 |

---

## 2. 数据依赖

### 2.1 输入数据源

| 表 | 关键字段 | 用途 |
|----|---------|------|
| `score_results` | `code`, `date`, `total_score`, `signal` | 确定信号触发日期 |
| `kline_indicators` | `code`, `ktype='1d'`, `date`, `close` | 获取买入/卖出价格 |

### 2.2 数据覆盖

- 股票数量：40 只（watchlist）
- 时间跨度：~900 个交易日（约 3.5 年）
- 评分范围：0-100 连续分，信号阈值：STRONG_BUY=80, BUY=60（v4）
- 价格频率：日线（`ktype='1d'`）

### 2.3 数据关联

```
score_results.code + score_results.date
  JOIN kline_indicators.code + kline_indicators.date
  WHERE kline_indicators.ktype = '1d'
```

主键天然对齐，无需额外 mapping。

---

## 3. 回测逻辑

### 3.1 信号触发规则

```python
# 伪代码
for each trading_day in date_range:
    score = score_results[code, trading_day].total_score
    if score >= score_threshold:
        trigger_signal(code, trading_day)
```

**触发条件**：
- `total_score >= score_threshold`（用户指定阈值，默认 40）
- 可选：连续触发去重（同一轮信号只取首日）

### 3.2 去重策略（冷却期）

当信号连续触发时，避免重复计数：

| 策略 | 说明 |
|------|------|
| `none` | 不去重，每天独立触发 |
| `holding` | 持仓期间不再触发新信号（冷却期=holding_period） |
| `custom` | 用户指定冷却天数 |

默认：`holding`（持仓期内不重复触发）

### 3.3 收益计算

```python
entry_price = kline[code, signal_date, '1d'].close      # 收盘买入
exit_date   = signal_date + holding_period trading days  # 持有 N 个交易日
exit_price  = kline[code, exit_date, '1d'].close         # 收盘卖出

return_pct  = (exit_price - entry_price) / entry_price * 100
```

**注意事项**：
- "N 个交易日"指 kline 表中按日期排序后的第 N 条记录（跳过非交易日）
- 若 exit_date 超出数据范围，该信号标记为 `incomplete`，不计入统计

### 3.4 完整流程

```
┌─────────────────────────────────────────────────────────┐
│  1. 查询 score_results 全量记录 (code, date_range)       │
│  2. 过滤 total_score >= threshold 的日期列表             │
│  3. 应用冷却期去重                                       │
│  4. 对每个信号日:                                        │
│     a. 从 kline_indicators 获取 entry_price (close)      │
│     b. 向前偏移 N 个交易日获取 exit_price (close)         │
│     c. 计算 return_pct                                   │
│  5. 聚合统计                                            │
└─────────────────────────────────────────────────────────┘
```

---

## 4. 输出指标

### 4.1 单次交易记录

| 字段 | 类型 | 说明 |
|------|------|------|
| `signal_date` | str | 信号触发日期 |
| `entry_price` | float | 买入价（当日收盘） |
| `exit_date` | str | 卖出日期 |
| `exit_price` | float | 卖出价（N 日后收盘） |
| `return_pct` | float | 收益率 % |
| `total_score` | int | 触发时评分 |
| `signal` | str | 原始信号（STRONG_BUY/BUY/NO_ACTION） |
| `status` | str | `complete` / `incomplete` |

### 4.2 汇总统计

| 指标 | 计算方式 |
|------|---------|
| `total_signals` | 信号触发总次数 |
| `completed_trades` | 有完整出场价格的交易数 |
| `win_count` | return_pct > 0 的次数 |
| `loss_count` | return_pct <= 0 的次数 |
| `win_rate` | win_count / completed_trades * 100 |
| `avg_return_pct` | 所有 complete 交易的平均收益率 |
| `median_return_pct` | 中位数收益率 |
| `max_return_pct` | 最大单次收益 |
| `min_return_pct` | 最大单次亏损 |
| `total_return_pct` | 累计收益率（假设等权） |
| `sharpe_like` | avg_return / std_return（简化夏普） |
| `profit_factor` | 总盈利 / 总亏损 绝对值 |

### 4.3 分组统计（可选）

- 按年度分组
- 按评分区间分组（40-60, 60-80, 80-100）
- 按市场温度分组（bull/neutral/bear）

---

## 5. API 设计

### 5.1 回测执行端点

```
GET /api/backtest/run
```

**Query Parameters**:

| 参数 | 类型 | 必填 | 默认值 | 约束 | 说明 |
|------|------|------|--------|------|------|
| `code` | str | 是 | — | Futu 格式 | 股票代码，如 US.SNDK |
| `threshold` | int | 否 | 40 | 1-100 | 评分阈值 |
| `holding_days` | int | 否 | 10 | 1-60 | 持有交易日数 |
| `cooldown` | str | 否 | `holding` | `none`/`holding`/`custom` | 去重策略 |
| `cooldown_days` | int | 否 | — | 1-60 | custom 模式冷却天数 |
| `start_date` | str | 否 | 最早数据日 | YYYY-MM-DD | 回测起始日 |
| `end_date` | str | 否 | 最新数据日 | YYYY-MM-DD | 回测截止日 |

**Response 200** (有数据):

```json
{
  "code": "US.SNDK",
  "params": {
    "threshold": 40,
    "holding_days": 10,
    "cooldown": "holding",
    "start_date": "2023-06-01",
    "end_date": "2026-05-05"
  },
  "summary": {
    "total_signals": 23,
    "completed_trades": 21,
    "win_count": 14,
    "loss_count": 7,
    "win_rate": 66.7,
    "avg_return_pct": 3.42,
    "median_return_pct": 2.85,
    "max_return_pct": 12.3,
    "min_return_pct": -5.1,
    "total_return_pct": 71.8,
    "sharpe_like": 0.82,
    "profit_factor": 2.45
  },
  "trades": [
    {
      "signal_date": "2024-01-15",
      "entry_price": 85.20,
      "exit_date": "2024-01-29",
      "exit_price": 89.50,
      "return_pct": 5.05,
      "total_score": 52,
      "signal": "NO_ACTION",
      "status": "complete"
    }
  ]
}
```

**Response 200** (无数据):

```json
{
  "data": null,
  "message": "No score data found for US.SNDK"
}
```

### 5.2 批量回测端点（v2）

```
GET /api/backtest/batch
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `codes` | str | 逗号分隔代码列表，或 `all` |
| `threshold` | int | 同上 |
| `holding_days` | int | 同上 |

返回每只股票的 summary（不含 trades 明细），用于横向对比。

### 5.3 参数扫描端点（v2）

```
GET /api/backtest/sweep
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `code` | str | 股票代码 |
| `threshold_range` | str | 如 `30,40,50,60,70,80` |
| `holding_range` | str | 如 `5,10,15,20,30` |

返回参数矩阵的胜率/平均收益热力图数据。

---

## 6. CLI 设计

### 6.1 命令定义

```python
@app.command()
def backtest(
    code: str = typer.Argument(..., help="股票代码 (Futu 格式, 如 US.SNDK)"),
    threshold: int = typer.Option(40, help="评分阈值 (1-100)"),
    holding_days: int = typer.Option(10, help="持有交易日数 (1-60)"),
    cooldown: str = typer.Option("holding", help="去重策略: none/holding/custom"),
    start_date: str = typer.Option(None, help="起始日期 YYYY-MM-DD"),
    end_date: str = typer.Option(None, help="截止日期 YYYY-MM-DD"),
    output: str = typer.Option("table", help="输出格式: table/json/csv"),
):
```

### 6.2 输出示例

```
$ trader-analysis backtest US.SNDK --threshold 40 --holding-days 10

Signal Backtest: US.SNDK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Parameters: threshold=40, holding=10d, cooldown=holding
Date Range: 2023-06-01 → 2026-05-05

Summary:
  Signals triggered:   23
  Completed trades:    21
  Win rate:            66.7%  (14W / 7L)
  Avg return:          +3.42%
  Median return:       +2.85%
  Best / Worst:        +12.3% / -5.1%
  Profit factor:       2.45
  Sharpe-like:         0.82

Recent Trades:
┌────────────┬────────┬────────────┬────────┬─────────┬───────┐
│ Signal Date│ Entry  │ Exit Date  │ Exit   │ Return  │ Score │
├────────────┼────────┼────────────┼────────┼─────────┼───────┤
│ 2026-04-10 │ 85.20  │ 2026-04-24 │ 89.50  │  +5.05% │  52   │
│ 2026-03-05 │ 78.40  │ 2026-03-19 │ 76.20  │  -2.81% │  45   │
│ ...        │ ...    │ ...        │ ...    │  ...    │ ...   │
└────────────┴────────┴────────────┴────────┴─────────┴───────┘
```

---

## 7. 核心模块设计

### 7.1 模块结构

```
src/trader_analysis/futu_strategy/
├── backtest.py          # 回测引擎核心逻辑
├── api_server.py        # 新增 /api/backtest/* 路由
├── storage.py           # 新增查询函数
└── ...

src/trader_analysis/
├── cli.py               # 新增 backtest 命令
└── ...
```

### 7.2 核心类/函数

```python
# backtest.py

@dataclass
class BacktestParams:
    code: str
    threshold: int = 40
    holding_days: int = 10
    cooldown: str = "holding"        # none | holding | custom
    cooldown_days: int | None = None # custom 模式
    start_date: str | None = None
    end_date: str | None = None

@dataclass
class Trade:
    signal_date: str
    entry_price: float
    exit_date: str | None
    exit_price: float | None
    return_pct: float | None
    total_score: int
    signal: str
    status: str  # complete | incomplete

@dataclass
class BacktestResult:
    code: str
    params: BacktestParams
    trades: list[Trade]
    summary: dict  # 汇总统计

def run_backtest(params: BacktestParams) -> BacktestResult:
    """主入口：执行单股回测"""
    ...
```

### 7.3 Storage 层新增函数

```python
# storage.py 新增

def query_all_scores(code: str, start_date: str = None, end_date: str = None) -> list[dict]:
    """查询某只股票在日期范围内的所有评分记录，按日期升序"""
    # SELECT code, date, total_score, signal FROM score_results
    # WHERE code = ? AND date >= ? AND date <= ?
    # ORDER BY date ASC
    ...

def query_close_prices(code: str, start_date: str = None, end_date: str = None) -> dict[str, float]:
    """查询某只股票日线收盘价，返回 {date: close} 字典"""
    # SELECT date, close FROM kline_indicators
    # WHERE code = ? AND ktype = '1d' AND date >= ? AND date <= ?
    # ORDER BY date ASC
    ...

def query_trading_dates(code: str, start_date: str = None, end_date: str = None) -> list[str]:
    """查询交易日历（从 kline 数据推导）"""
    # SELECT DISTINCT date FROM kline_indicators
    # WHERE code = ? AND ktype = '1d' AND date >= ? AND date <= ?
    # ORDER BY date ASC
    ...
```

### 7.4 算法流程（详细）

```python
def run_backtest(params: BacktestParams) -> BacktestResult:
    # Step 1: 获取数据
    scores = query_all_scores(params.code, params.start_date, params.end_date)
    prices = query_close_prices(params.code, params.start_date, params.end_date)
    trading_dates = query_trading_dates(params.code, params.start_date, params.end_date)

    # Step 2: 构建交易日索引 (date -> position)
    date_index = {d: i for i, d in enumerate(trading_dates)}

    # Step 3: 筛选信号日
    signal_dates = [s for s in scores if s["total_score"] >= params.threshold]

    # Step 4: 应用冷却期
    filtered_signals = apply_cooldown(signal_dates, params)

    # Step 5: 计算每笔交易
    trades = []
    for signal in filtered_signals:
        entry_date = signal["date"]
        entry_price = prices.get(entry_date)
        if entry_price is None:
            continue

        # 计算出场日
        entry_idx = date_index.get(entry_date)
        exit_idx = entry_idx + params.holding_days
        if exit_idx >= len(trading_dates):
            trades.append(Trade(..., status="incomplete"))
            continue

        exit_date = trading_dates[exit_idx]
        exit_price = prices[exit_date]
        return_pct = (exit_price - entry_price) / entry_price * 100

        trades.append(Trade(
            signal_date=entry_date,
            entry_price=entry_price,
            exit_date=exit_date,
            exit_price=exit_price,
            return_pct=return_pct,
            total_score=signal["total_score"],
            signal=signal["signal"],
            status="complete",
        ))

    # Step 6: 计算汇总统计
    summary = calculate_summary(trades)

    return BacktestResult(code=params.code, params=params, trades=trades, summary=summary)
```

---

## 8. 边界情况处理

| 场景 | 处理方式 |
|------|---------|
| 信号日无价格数据 | 跳过该信号，不计入统计 |
| 出场日超出数据范围 | 标记 `status=incomplete`，不计入汇总 |
| score_results 无该股票记录 | 返回 `{"data": null, "message": "..."}` |
| 阈值过高导致无信号 | 返回空 trades + summary 全零 |
| 同一天多条评分记录 | 不可能（PRIMARY KEY 约束） |
| 停牌日无 kline 数据 | 交易日历自动跳过（基于 kline 实际数据） |
| 代码格式错误 | FastAPI Query validation / Typer 参数校验 |

---

## 9. 性能考量

### 9.1 数据量估算

| 维度 | 数量 |
|------|------|
| 单股评分记录 | ~900 条 |
| 单股日线数据 | ~900 条 |
| 单次回测信号触发（threshold=40） | 估计 50-200 次 |
| 批量回测（40 股） | ~36,000 条评分 + ~36,000 条日线 |

### 9.2 查询优化

- 单股回测：2 次 SQLite 查询（scores + prices），毫秒级响应
- 批量回测：每股独立查询，总耗时 < 1s（SQLite 本地文件）
- 无需缓存层：数据量小，每次重算开销极低
- 使用 `dict` 索引价格查找：O(1) 而非 O(n) 搜索

### 9.3 内存占用

- 单股：~900 scores + ~900 prices ≈ 几十 KB
- 全量批量：40 * 上述 ≈ 几 MB
- 无需分页或流式处理

---

## 10. 扩展方向（v2+）

### 10.1 多因子回测

- 结合市场温度（`market_score.composite_score`）过滤
- 评分分维度回测（仅 RSI 触发 / 仅 MACD 触发）
- breakdown 子分数阈值组合

### 10.2 持仓策略变体

| 策略 | 说明 |
|------|------|
| 固定持有 | 买入后持有 N 天（v1 实现） |
| 止盈止损 | 达到 +X% 或 -Y% 提前退出 |
| 跟踪止损 | 最高点回撤 Z% 退出 |
| 信号退出 | 评分降至某阈值以下退出 |

### 10.3 组合回测

- 等权组合：所有触发信号的股票等权买入
- 按评分加权：评分越高仓位越大
- 资金管理：固定资金池，考虑仓位限制

### 10.4 可视化

- 收益曲线图（累计收益 vs 时间）
- 参数热力图（threshold x holding_days → win_rate/avg_return）
- 信号标注到 K 线图

---

## 11. 实现优先级

| 阶段 | 范围 | 预期产出 |
|------|------|---------|
| **P0** | 单股 + 固定持有 + CLI | `backtest` 命令可用 |
| **P1** | API 端点 + 冷却期策略 | `/api/backtest/run` 上线 |
| **P2** | 批量回测 + 参数扫描 | `/api/backtest/batch` + `/sweep` |
| **P3** | 止盈止损 + 市场温度联合 | 高级策略 |
| **P4** | 可视化 + 组合回测 | 数据展示 |

---

## 12. 验收标准（P0）

- [ ] `trader-analysis backtest US.SNDK --threshold 40 --holding-days 10` 正确输出统计结果
- [ ] 回测结果可复现（相同输入 → 相同输出）
- [ ] 边界情况不 crash（无数据、阈值过高、holding 超范围）
- [ ] 单股回测响应时间 < 500ms
- [ ] 代码覆盖：核心计算逻辑有单元测试
