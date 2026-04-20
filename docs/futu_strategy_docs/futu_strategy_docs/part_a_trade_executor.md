# Part A — 交易执行与调度（trade_executor.py）

> 本模块根据 scorer.py 的评分结果执行模拟盘买入操作，并负责定时调度策略的运行。

---

## 功能清单

### 交易执行

| # | 功能 | 数据来源 |
|---|------|---------|
| D1 | 获取当前价格 | 富途 `get_market_snapshot`（外部数据） |
| D2 | 计算买入数量 | 自实现（固定金额 ÷ 当前价格） |
| D3 | 查询当前持仓（防重复买入） | 富途 `position_list_query`（外部数据） |
| D4 | 执行下单 | 富途 `place_order`（外部数据） |

### 调度机制

| # | 功能 | 实现方式 |
|---|------|---------|
| E1 | 每日收盘后自动运行策略 | 系统定时任务 / schedule 库 |
| E2 | 每日收盘后自动增量更新存储层 | 同上 |
| E3 | 支持手动触发（测试阶段） | 命令行参数 |

---

## 实现思路

### 交易执行
- 收到 scorer 的评分结果后，`STRONG_BUY` 和 `BUY` 触发下单，`NO_ACTION` 跳过
- 下单前查持仓防重复（已持有且非 `STRONG_BUY` 则跳过）
- 默认使用模拟环境 `TrdEnv.SIMULATE`

### 调度机制
- 策略基于日线/周线数据，**不需要实时 tick 触发**，每日收盘后运行一次即可
- 推荐运行时间：美股 北京时间次日 06:00，港股 每日 17:00

---

## 具体实现方案

### 仓位配置（`config.py`）

```python
POSITION_CONFIG = {
    "STRONG_BUY": {"type": "fixed_amount", "amount_usd": 2000},
    "BUY":        {"type": "fixed_amount", "amount_usd": 1000},
}
```

### 交易执行函数（`trade_executor.py`，自实现，调用 Futu 交易 API）

```python
def execute_trade(signal: dict, acc_id: int, trd_ctx, quote_ctx):
    """
    signal:    scorer.py 返回的评分结果
    acc_id:    模拟账户 ID
    trd_ctx:   OpenSecTradeContext（复用，不要每次新建）
    quote_ctx: OpenQuoteContext（获取快照价格用）
    """
    if signal['signal'] == 'NO_ACTION':
        return

    code = signal['code']

    # 1. 获取快照价格
    ret, df = quote_ctx.get_market_snapshot([code])
    current_price = float(df['last_price'].iloc[0])

    # 2. 计算数量
    amount = POSITION_CONFIG[signal['signal']]['amount_usd']
    qty = int(amount / current_price)

    # 3. 检查持仓（防重复）
    ret, positions = trd_ctx.position_list_query(
        code=code, trd_env=TrdEnv.SIMULATE, acc_id=acc_id, refresh_cache=True
    )
    if ret == RET_OK and not positions.empty:
        if signal['signal'] != 'STRONG_BUY':
            return  # 已持有且非强烈买入，跳过

    # 4. 下单
    ret, data = trd_ctx.place_order(
        price=current_price,
        qty=qty,
        code=code,
        trd_side=TrdSide.BUY,
        order_type=OrderType.NORMAL,
        trd_env=TrdEnv.SIMULATE,
        acc_id=acc_id
    )

    # 5. 写交易日志
    ...
```

### 模拟账户 acc_id 获取

运行开始时调用一次，后续复用：

```python
ret, acc_list = trd_ctx.get_acc_list()
sim_accounts = acc_list[acc_list['trd_env'] == 'SIMULATE']
acc_id = int(sim_accounts.iloc[0]['acc_id'])
```

---

### 调度方案

**方式一：`schedule` 库（自实现，简单场景）**

```python
import schedule, time

schedule.every().day.at("06:00").do(run_strategy)   # 美股
schedule.every().day.at("17:00").do(run_strategy)   # 港股

while True:
    schedule.run_pending()
    time.sleep(60)
```

**方式二：系统定时任务（推荐生产使用）**

- **Windows**：任务计划程序，每日定时执行 `python strategy_runner.py`
- **Linux/Mac**：`crontab -e`，添加 `0 6 * * * python /path/strategy_runner.py`

**方式三：手动触发（测试阶段）**

```bash
python strategy_runner.py --codes US.AAPL US.TSLA HK.00700
```
