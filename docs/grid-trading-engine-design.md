# 日内网格交易引擎 技术设计文档

> 最后更新：2026-05-10 | 版本：v1.0 | 状态：P0 部分实现（详见各节 ⚠️ 标注及文末「实现现状核对表」）

---

## 1. 概述

### 1.1 目标

实现一个日内网格自动交易引擎，基于富途 OpenD 实时行情推送，当价格触达预设网格线时自动下单。支持模拟盘/实盘切换，首期只跑单只美股标的（GLD）。

### 1.2 什么是网格策略

```
价格
 ↑
 │  ────── 网格线 5 (卖出)  $248
 │  ────── 网格线 4 (卖出)  $246
 │  ────── 网格线 3 (卖出)  $244   ← 当前价
 │  ────── 网格线 2 (买入)  $242
 │  ────── 网格线 1 (买入)  $240
 │  ────── 网格线 0 (买入)  $238
 ↓
```

- 价格下穿网格线 → 买入固定手数
- 价格上穿网格线 → 卖出固定手数
- 在震荡行情中反复吃差价

### 1.3 设计原则

| 原则 | 说明 |
|------|------|
| 安全第一 | 模拟盘验证通过后才切实盘；单日最大亏损熔断 |
| 实时驱动 | 行情推送回调触发下单，非轮询 |
| 可观测 | 所有交易记录入库，API 可查 |
| 盘中限定 | 仅在美股常规交易时段运行（09:30-16:00 ET） |
| 独立进程 | 通过 `trader-analysis grid-start` 启动，与 API 服务互不影响 |

---

## 2. 架构

### 2.1 系统架构图

```
┌─────────────────────────────────────────────────────┐
│                  Futu OpenD (本地)                    │
│    实时行情推送 / 下单接口 / 订单状态推送              │
└──────────────┬──────────────────────┬───────────────┘
               │ 价格推送              │ 订单回报
               ▼                      ▼
┌──────────────────────────────────────────────────────┐
│              Grid Trading Engine (长驻进程)            │
│                                                      │
│  ┌────────────┐  ┌────────────┐  ┌───────────────┐  │
│  │ 行情监听器  │  │ 网格决策器  │  │  订单执行器    │  │
│  │ (Callback) │→ │ (Strategy) │→ │  (Executor)   │  │
│  └────────────┘  └────────────┘  └───────────────┘  │
│         │               │               │            │
│         └───────────────┼───────────────┘            │
│                         ▼                            │
│                  ┌─────────────┐                     │
│                  │  状态管理器   │                     │
│                  │ (StateManager)│                    │
│                  └──────┬──────┘                     │
│                         │                            │
└─────────────────────────┼────────────────────────────┘
                          ▼
                   ┌─────────────┐
                   │   SQLite    │
                   │ (共享 DB)    │
                   └─────────────┘
```

### 2.2 模块职责

| 模块 | 职责 |
|------|------|
| **行情监听器** | 订阅实时报价，价格变动时触发回调 |
| **网格决策器** | 判断价格是否穿越网格线，决定买/卖/不动 |
| **订单执行器** | 调用富途下单 API，管理订单生命周期 |
| **状态管理器** | 维护网格状态、持仓、交易记录，持久化到 SQLite |
| **风控模块** | 盘中时段控制、最大仓位、单日熔断 |

---

## 3. 数据模型

### 3.1 新表：`grid_config`（网格配置）

```sql
CREATE TABLE IF NOT EXISTS grid_config (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT NOT NULL,             -- US.GLD
    name            TEXT DEFAULT '',           -- 配置名称（便于区分多组配置）
    status          TEXT NOT NULL DEFAULT 'stopped',  -- running / stopped / paused
    env             TEXT NOT NULL DEFAULT 'simulate', -- simulate / live

    -- 网格参数
    price_upper     REAL NOT NULL,            -- 网格上界
    price_lower     REAL NOT NULL,            -- 网格下界
    grid_count      INTEGER NOT NULL,         -- 网格数量（线数 = grid_count + 1）
    grid_spacing    REAL,                     -- 每格间距（自动计算: (upper-lower)/grid_count）
    order_qty       INTEGER NOT NULL,         -- 每格下单股数

    -- 风控参数
    max_position    INTEGER NOT NULL,         -- 最大持仓股数
    daily_loss_limit REAL DEFAULT -500.0,     -- 单日最大亏损(美元)，触发熔断
    max_orders_per_day INTEGER DEFAULT 50,    -- 单日最大下单次数

    -- 时间控制
    trading_start   TEXT DEFAULT '09:30',     -- 开始交易时间 (ET)
    trading_end     TEXT DEFAULT '15:50',     -- 停止下单时间 (ET, 留10分钟收尾)

    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 3.2 新表：`grid_orders`（交易记录）

> ⚠️ **状态：表结构已实现，但 `status` 取值与代码不符**。DDL 与 `state_manager.py:34-51` 一致；但代码实际写入的 `status` 值为 `submitted`（下单成功，`engine.py:176`）、`failed`、`filled`（`update_order_fill`，`state_manager.py:259`），**并未使用** `partial` / `cancelled`，且枚举中漏了 `submitted`。

```sql
CREATE TABLE IF NOT EXISTS grid_orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id       INTEGER NOT NULL,         -- 关联 grid_config.id
    code            TEXT NOT NULL,
    env             TEXT NOT NULL,            -- simulate / live

    -- 订单信息
    direction       TEXT NOT NULL,            -- BUY / SELL
    grid_level      INTEGER NOT NULL,         -- 触发的网格层级 (0-based)
    grid_price      REAL NOT NULL,            -- 网格线价格
    order_qty       INTEGER NOT NULL,         -- 下单数量
    order_id        TEXT,                     -- 富途订单号
    fill_price      REAL,                     -- 成交均价
    fill_qty        INTEGER,                  -- 成交数量
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending/filled/partial/cancelled/failed
    pnl             REAL,                     -- 本次交易盈亏（卖出时计算）

    triggered_at    TEXT NOT NULL,            -- 信号触发时间
    filled_at       TEXT,                     -- 成交时间
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_grid_orders_config ON grid_orders(config_id);
CREATE INDEX IF NOT EXISTS idx_grid_orders_time ON grid_orders(triggered_at);
```

### 3.3 新表：`grid_state`（运行时状态）

```sql
CREATE TABLE IF NOT EXISTS grid_state (
    config_id       INTEGER PRIMARY KEY,      -- 关联 grid_config.id
    current_position INTEGER DEFAULT 0,       -- 当前持仓股数
    cost_basis      REAL DEFAULT 0.0,         -- 持仓成本
    daily_pnl       REAL DEFAULT 0.0,         -- 当日已实现盈亏
    daily_trades    INTEGER DEFAULT 0,        -- 当日交易次数
    last_price      REAL,                     -- 最新价格
    last_update     TEXT,                     -- 最后更新时间
    grid_status     TEXT DEFAULT '{}',        -- JSON: 每层网格的状态 {"0":"bought","1":"empty",...}

    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

---

## 4. 网格策略逻辑

### 4.1 网格线计算

```python
def calculate_grid_lines(config: GridConfig) -> list[float]:
    """
    生成等间距网格线列表（从低到高）。

    例: upper=250, lower=240, grid_count=5
    间距 = (250 - 240) / 5 = 2.0
    网格线 = [240.0, 242.0, 244.0, 246.0, 248.0, 250.0]  # 6条线
    """
    spacing = (config.price_upper - config.price_lower) / config.grid_count
    return [config.price_lower + i * spacing for i in range(config.grid_count + 1)]
```

### 4.2 信号触发逻辑

> ⚠️ **状态：部分实现（签名不一致）**。实际函数名为 `detect_crossing`（非 `on_price_update`），位于 `grid_trader/strategy.py:18`。引擎侧另有 `GridEngine.on_price_update(self, code, price)`（`engine.py:118`），只接收单个价格，与本节示例无关。另：实现取「距离当前价最近的那条穿越线」（`strategy.py:26-40`），而非本节示例中按网格顺序返回第一条——跳空时的行为请以代码为准。

```python
def on_price_update(price: float, prev_price: float, grid_lines: list[float]) -> Signal | None:
    """
    判断价格是否穿越网格线。

    规则：
    - 价格从上方穿越某网格线（下穿）→ BUY
    - 价格从下方穿越某网格线（上穿）→ SELL
    - 未穿越任何网格线 → None

    穿越判定：prev_price 在线的一侧，price 在线的另一侧（或刚好触达）
    """
    for i, line in enumerate(grid_lines):
        # 下穿: prev >= line and price < line
        if prev_price >= line and price < line:
            return Signal(direction="BUY", grid_level=i, grid_price=line)
        # 上穿: prev <= line and price > line
        if prev_price <= line and price > line:
            return Signal(direction="SELL", grid_level=i, grid_price=line)
    return None
```

### 4.3 网格状态管理

> ⚠️ **状态：部分实现（名称/返回类型不一致）**。实际函数为 `should_execute(signal, grid_status) -> bool`（`strategy.py:45`），不叫 `decide_action`，也不返回 `Action` 对象，仅返回是否执行的布尔值。状态枚举 `empty` / `bought` 与代码一致。

每层网格有状态：

| 状态 | 含义 | 下穿时动作 | 上穿时动作 |
|------|------|-----------|-----------|
| `empty` | 该层无持仓 | 买入 → 变为 `bought` | 不动（无货可卖） |
| `bought` | 该层已买入 | 不动（不加仓） | 卖出 → 变为 `empty` |

```python
def decide_action(signal: Signal, grid_status: dict) -> Action | None:
    """
    结合网格状态决定是否执行。

    - BUY 信号 + 该层 empty → 执行买入
    - BUY 信号 + 该层 bought → 跳过（已持有）
    - SELL 信号 + 该层 bought → 执行卖出
    - SELL 信号 + 该层 empty → 跳过（无持仓）
    """
```

### 4.4 完整决策流程

> ⚠️ **状态：部分实现（步骤顺序与代码相反）**。实现顺序为：穿越检测 → **网格状态检查**（`should_execute`）→ **风控检查**（`check_risk`）→ 下单（`engine.py:138-156`）。即代码先判该层可否执行、再判风控，与下方流程图顺序相反。

```
价格推送 (real-time callback)
    │
    ▼
是否在交易时段？ ─── 否 ──→ 忽略
    │ 是
    ▼
是否穿越网格线？ ─── 否 ──→ 更新 last_price
    │ 是
    ▼
风控检查：
  - 仓位是否超限？
  - 当日亏损是否触发熔断？
  - 当日交易次数是否超限？
    │ 通过
    ▼
网格状态检查：
  - 该层是否可执行？
    │ 可执行
    ▼
下单执行 → 更新状态 → 写入 grid_orders
```

---

## 5. 富途 API 对接

### 5.1 使用的接口

> ⚠️ **状态：部分实现**。代码实际只用到 `OpenQuoteContext.subscribe()`（`engine.py:73`）、`StockQuoteHandlerBase`（`quote_handler.py:17`）、`OpenSecTradeContext` / `place_order()`（`executor.py:30`）。表中 `cancel_order()`、`TradeOrderHandlerBase`、`position_list_query()` 在 `grid_trader/` 中**未找到任何调用**，属设计意图。

| 模块 | 接口 | 用途 |
|------|------|------|
| 行情 | `OpenQuoteContext.subscribe()` | 订阅实时报价 |
| 行情 | `StockQuoteHandlerBase` | 最新价推送回调 |
| 交易 | `OpenSecTradeContext` | 交易连接（美股） |
| 交易 | `place_order()` | 下单 |
| 交易 | `cancel_order()` | 撤单 |
| 交易 | `TradeOrderHandlerBase` | 订单状态推送回调 |
| 交易 | `position_list_query()` | 查询持仓（启动时同步） |

### 5.2 环境切换

> ⚠️ **状态：部分实现（写法与代码不同）**。代码在创建交易连接时传的是 `filter_trdmarket=TrdMarket.US`（`engine.py:62-66`），`trd_env` 则在下单时传入 `place_order(..., trd_env=trd_env)`（`executor.py:28-38`），并非本节示例那样在建连时传 `trd_env`。

```python
from futu import TrdEnv

# 模拟盘
trd_ctx = OpenSecTradeContext(host=OPEND_HOST, port=OPEND_PORT, trd_env=TrdEnv.SIMULATE)

# 实盘
trd_ctx = OpenSecTradeContext(host=OPEND_HOST, port=OPEND_PORT, trd_env=TrdEnv.REAL)
```

配置中 `env` 字段控制：
- `simulate` → `TrdEnv.SIMULATE`（模拟盘，无真实资金风险）
- `live` → `TrdEnv.REAL`（实盘，真金白银）

### 5.3 行情订阅

> ⚠️ **状态：部分实现（写法不同）**。代码通过工厂 `create_quote_handler(engine)` 返回闭包式 handler（`quote_handler.py:10-30`），回调内直接调用 `engine.on_price_update(code, float(price))`；并非本节所示的 `self.engine` 属性写法。`subscribe([code],[SubType.QUOTE])` 与代码一致。

```python
from futu import OpenQuoteContext, SubType, StockQuoteHandlerBase

class GridQuoteHandler(StockQuoteHandlerBase):
    """实时报价回调"""

    def on_recv_rsp(self, rsp_pb):
        ret, data = super().on_recv_rsp(rsp_pb)
        if ret == 0:
            for _, row in data.iterrows():
                price = row["last_price"]
                code = row["code"]
                self.engine.on_price_update(code, price)

# 订阅
quote_ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
quote_ctx.set_handler(GridQuoteHandler())
quote_ctx.subscribe([code], [SubType.QUOTE])
```

### 5.4 下单执行

> ⚠️ **状态：部分实现（签名不一致）**。实际签名为 `place_grid_order(trd_ctx, code, direction, qty, price, env) -> str | None`（`executor.py:10`），多一个 `env` 参数；失败时返回 `None` 并记录日志，**不抛 `OrderError`**（代码中不存在 `OrderError` 类）。

```python
from futu import TrdSide, OrderType, TrdMarket

def place_grid_order(trd_ctx, code: str, direction: str, qty: int, price: float) -> str:
    """
    下限价单。

    Args:
        direction: "BUY" / "SELL"
        qty: 股数
        price: 限价（使用网格线价格，确保成交在网格附近）

    Returns:
        order_id: 富途订单号
    """
    side = TrdSide.BUY if direction == "BUY" else TrdSide.SELL
    ret, data = trd_ctx.place_order(
        price=price,
        qty=qty,
        code=code,
        trd_side=side,
        order_type=OrderType.NORMAL,  # 限价单
        trd_market=TrdMarket.US,
    )
    if ret == 0:
        return str(data["order_id"].iloc[0])
    else:
        raise OrderError(f"Place order failed: {data}")
```

### 5.5 订单状态回调

> ⚠️ **状态：设计稿，代码中未实现**（截至 2026-10-12 在 `grid_trader/` 中未找到 `order_handler.py`、`TradeOrderHandlerBase`、`on_order_update` 的任何实现）。引擎对成交采用「下单即视为立即成交」的简化处理（`engine.py:189-220`），不订阅订单状态推送。

```python
class GridOrderHandler(TradeOrderHandlerBase):
    """订单状态推送"""

    def on_recv_rsp(self, rsp_pb):
        ret, data = super().on_recv_rsp(rsp_pb)
        if ret == 0:
            for _, row in data.iterrows():
                order_id = str(row["order_id"])
                status = row["order_status"]
                fill_price = row.get("dealt_avg_price")
                fill_qty = row.get("dealt_qty")
                self.engine.on_order_update(order_id, status, fill_price, fill_qty)
```

---

## 6. 风控模块

### 6.1 风控规则

> ⚠️ **状态：部分实现**。前 4 项（最大持仓、单日亏损熔断、单日交易次数、交易时段限制）已在 `risk_control.py:26-46` / `risk_control.py:14-23` 实现；末项「收盘前平仓（可选）」在代码中**未找到实现**，属设计意图。另注意：实现中「单日亏损熔断」只返回拦截原因、**不会把 config 状态置为 `paused`**（`status` 目前仅由启动/停止写入 `running`/`stopped`）。

| 规则 | 参数 | 触发后动作 |
|------|------|-----------|
| 最大持仓 | `max_position` 股 | 禁止新的 BUY |
| 单日亏损熔断 | `daily_loss_limit` 美元 | 停止所有交易，状态置为 `paused` |
| 单日交易次数 | `max_orders_per_day` 次 | 停止新下单 |
| 交易时段限制 | `trading_start` ~ `trading_end` | 盘外不下单 |
| 收盘前平仓（可选） | `trading_end` 前 10 分钟 | 可配置是否尾盘全平 |

### 6.2 时段控制

```python
import pytz
from datetime import datetime

ET = pytz.timezone("US/Eastern")

def is_trading_hours(config: GridConfig) -> bool:
    """判断当前是否在交易时段内"""
    now_et = datetime.now(ET)

    # 周末不交易
    if now_et.weekday() >= 5:
        return False

    current_time = now_et.strftime("%H:%M")
    return config.trading_start <= current_time <= config.trading_end
```

### 6.3 盈亏计算

> ⚠️ **状态：部分实现（无独立函数）**。代码中**没有** `calculate_pnl` 函数；盈亏与成本在 `engine._execute_signal` 内联计算（`engine.py:194-215`），公式与本节的 `(fill_price - cost_basis) * qty` 一致，采用平均成本法。

```python
def calculate_pnl(direction: str, fill_price: float, qty: int, cost_basis: float) -> float:
    """
    卖出时计算本次盈亏。

    采用 FIFO 或平均成本法（v1 用平均成本）。
    pnl = (fill_price - avg_cost) * qty  (SELL时)
    """
    if direction == "SELL":
        return (fill_price - cost_basis) * qty
    return 0.0
```

---

## 7. 进程生命周期

### 7.1 启动流程

> ⚠️ **状态：部分实现**。步骤 1/3/5/6/7/8 已在 `engine.py:35-97` 实现（加载配置、连接 OpenD、订阅行情、注册 handler、置 `running`、进入事件循环）。步骤 2「校验参数合法性」仅在建配置时校验 `upper > lower`（`cli.py:467`），引擎启动时不校验；步骤 4「同步当前持仓（从富途查询）」**未实现**（无 `position_list_query` 调用）。

```
trader-analysis grid-start --config-id 1
    │
    ├─ 1. 加载 grid_config 配置
    ├─ 2. 校验参数合法性
    ├─ 3. 连接 OpenD（行情 + 交易）
    ├─ 4. 同步当前持仓（从富途查询，与 grid_state 对齐）
    ├─ 5. 订阅实时行情
    ├─ 6. 注册回调 handler
    ├─ 7. 设置 config.status = 'running'
    └─ 8. 进入事件循环（阻塞，等待行情推送）
```

### 7.2 停止流程

> ⚠️ **状态：部分实现**。`engine.stop()`（`engine.py:99-116`）实现了步骤 1/3/4/5/6（取消订阅随 `quote_ctx.close()`、保存状态、置 `stopped`、断开连接、退出）；步骤 2「撤销所有未成交挂单」**未实现**（无 `cancel_order` 调用）。外部停止：`grid-stop` 只把 `status` 写为 `stopped`（`cli.py:534`），引擎在事件循环中轮询到后退出（`engine.py:91-94`）。

```
Ctrl+C / trader-analysis grid-stop --config-id 1
    │
    ├─ 1. 取消行情订阅
    ├─ 2. 撤销所有未成交挂单
    ├─ 3. 保存当前状态到 grid_state
    ├─ 4. 设置 config.status = 'stopped'
    ├─ 5. 断开 OpenD 连接
    └─ 6. 进程退出
```

### 7.3 每日重置

> ⚠️ **状态：部分实现**。`state_manager.daily_reset(config_id)` 函数已存在（`state_manager.py:212`，按 `config_id` 重置），但**没有任何地方调用它**——引擎中不存在「开盘自动重置」的触发逻辑，属设计意图。

每个交易日开盘前自动重置日内计数器：

```python
def daily_reset(state: GridState):
    """交易日开盘时重置"""
    state.daily_pnl = 0.0
    state.daily_trades = 0
```

---

## 8. CLI 设计

### 8.1 命令

> ✅ **状态：已实现**。`grid-create` / `grid-start` / `grid-stop` / `grid-status` 四条命令均在 `cli.py` 中（`cli.py:452`、`491`、`521`、`914`）。差异：`grid-create` 实际还支持 `--name` 与 `--daily-loss-limit`（`cli.py:461-462`），本节示例未列出；`grid-start` 对 `env=live` 有二次确认（`cli.py:512-515`）。

```python
@app.command()
def grid_start(
    config_id: int = typer.Argument(..., help="网格配置 ID"),
):
    """启动网格交易引擎（长驻进程）"""

@app.command()
def grid_stop(
    config_id: int = typer.Argument(..., help="网格配置 ID"),
):
    """停止网格交易引擎（发送停止信号）"""

@app.command()
def grid_create(
    code: str = typer.Option(..., help="标的代码 (US.GLD)"),
    upper: float = typer.Option(..., help="网格上界"),
    lower: float = typer.Option(..., help="网格下界"),
    grid_count: int = typer.Option(10, help="网格数量"),
    order_qty: int = typer.Option(10, help="每格下单股数"),
    max_position: int = typer.Option(100, help="最大持仓股数"),
    env: str = typer.Option("simulate", help="环境: simulate/live"),
):
    """创建网格交易配置"""

@app.command()
def grid_status(
    config_id: int = typer.Argument(None, help="配置 ID，不传则显示全部"),
):
    """查看网格运行状态"""
```

### 8.2 使用示例

> ⚠️ **输出与代码略有出入**：`grid-create` 实际输出为多行（`cli.py:484-488`），非单行 `Grid config #1 created. spacing=$2.00, lines=11`；`grid-status` 实际还会打印 `Range:` 行（`cli.py:948`）。

```bash
# 创建配置（GLD，240-260，10格，每格10股，模拟盘）
trader-analysis grid-create \
  --code US.GLD \
  --upper 260 \
  --lower 240 \
  --grid-count 10 \
  --order-qty 10 \
  --max-position 100 \
  --env simulate

# 输出: Grid config #1 created. spacing=$2.00, lines=11

# 启动
trader-analysis grid-start 1

# 查看状态
trader-analysis grid-status 1

# 输出:
# Grid #1: US.GLD [RUNNING] simulate
# Price: $248.50 | Position: 30 shares | Cost: $245.20
# Today: 6 trades | PnL: +$42.50
# Grid: [B][B][B][ ][ ][ ][ ][ ][ ][ ][ ]
#         240 242 244 246 248 250 252 254 256 258 260

# 停止
trader-analysis grid-stop 1
```

---

## 9. API 端点

### 9.1 网格状态查询

> ⚠️ **状态：已实现，响应结构与本文略异**。端点存在（`api_server.py:538`）。实际响应在 `params` 中额外包含 `max_position`，并在顶层额外返回 `grid_lines`（网格线数组，`api_server.py:565`、`575`）；配置不存在时返回 `{"data": null, "message": ...}`。

```
GET /api/grid/status?config_id=1
```

**Response 200:**
```json
{
  "config_id": 1,
  "code": "US.GLD",
  "status": "running",
  "env": "simulate",
  "params": {
    "price_upper": 260.0,
    "price_lower": 240.0,
    "grid_count": 10,
    "grid_spacing": 2.0,
    "order_qty": 10
  },
  "state": {
    "current_position": 30,
    "cost_basis": 245.20,
    "daily_pnl": 42.50,
    "daily_trades": 6,
    "last_price": 248.50,
    "grid_status": {"0":"bought","1":"bought","2":"bought","3":"empty","4":"empty"}
  }
}
```

### 9.2 交易记录查询

> ⚠️ **状态：已实现，`total` 语义不同**。端点存在（`api_server.py:579`）。实际 `total = len(orders)`（`api_server.py:589`），即**本次返回条数**（≤ `limit`），而非库中总记录数；本文示例 `total:128 / limit:50` 会给人「总数」的误读。

```
GET /api/grid/orders?config_id=1&limit=50
```

**Response 200:**
```json
{
  "total": 128,
  "orders": [
    {
      "id": 128,
      "direction": "SELL",
      "grid_level": 4,
      "grid_price": 248.0,
      "fill_price": 248.05,
      "fill_qty": 10,
      "pnl": 28.50,
      "status": "filled",
      "triggered_at": "2026-05-06 14:23:15",
      "filled_at": "2026-05-06 14:23:16"
    }
  ]
}
```

### 9.3 网格配置管理

> ⚠️ **状态：设计稿，代码中未实现**（截至 2026-10-12 在 `api_server.py` 中未找到 `POST/PATCH/DELETE /api/grid/config` 与 `GET /api/grid/configs`）。当前网格相关 API 仅 `GET /api/grid/status` 与 `GET /api/grid/orders` 两个（`api_server.py:538`、`579`）。配置的增删改用 CLI（`grid-create`）。

```
POST   /api/grid/config          # 创建配置
PATCH  /api/grid/config/{id}     # 修改配置（仅 stopped 状态可改）
DELETE /api/grid/config/{id}     # 删除配置
GET    /api/grid/configs         # 列出所有配置
```

---

## 10. 模块结构

### 10.1 新增文件

> ⚠️ **状态：部分实现**。实际存在的文件为：`__init__.py`、`engine.py`、`models.py`、`strategy.py`、`risk_control.py`、`executor.py`、`quote_handler.py`、`state_manager.py`。本列表中的 **`order_handler.py` 不存在**（订单回调未实现，见 §5.5）。

```
src/trader_analysis/futu_strategy/grid_trader/
├── __init__.py
├── engine.py              # 主引擎：组装各模块、事件循环
├── strategy.py            # 网格决策逻辑
├── executor.py            # 富途下单封装
├── risk_control.py        # 风控规则
├── quote_handler.py       # 行情回调
├── order_handler.py       # 订单回调
├── state_manager.py       # 状态管理 + DB 读写
└── models.py              # 数据类定义 (GridConfig, Signal, Trade...)
```

### 10.2 修改文件

> ⚠️ **状态：部分实现（落库位置与本文不同）**。3 张网格表的 DDL **不在 `storage.py`**，而在 `grid_trader/state_manager.py:13-67`（`_GRID_DDL`），`storage.py` 中未找到 `grid_config`/`grid_orders`/`grid_state`。表结构与 §3 描述一致；`storage.py` 仅新增了回测相关查询函数（与网格无关）。

| 文件 | 改动 |
|------|------|
| `state_manager.py` | 新增 3 张表 DDL（grid_config/orders/state）— 注：本文原写 `storage.py`，实为 `grid_trader/state_manager.py` |
| `cli.py` | 新增 grid-create/start/stop/status 命令 |
| `api_server.py` | 新增 `/api/grid/*` 路由 |
| `config.py` | 新增 `OPEND_HOST`/`OPEND_PORT` 引用（已存在，无需改） |

---

## 11. 模拟盘 vs 实盘

### 11.1 切换方式

唯一区别：`TrdEnv.SIMULATE` vs `TrdEnv.REAL`

```python
trd_env = TrdEnv.SIMULATE if config.env == "simulate" else TrdEnv.REAL
```

### 11.2 验证流程

```
1. grid-create --env simulate  → 创建模拟盘配置
2. grid-start 1               → 跑一整天模拟盘
3. 检查交易记录、盈亏、风控是否符合预期
4. 确认无误后：
   PATCH /api/grid/config/1 {"env": "live"}  → 切换为实盘
5. grid-start 1               → 实盘运行
```

### 11.3 安全措施

- 实盘模式启动时打印显眼警告：`⚠️ LIVE TRADING MODE - REAL MONEY AT RISK`
- CLI 实盘启动需二次确认：`Are you sure? (y/N)`
- 首次实盘建议用最小 `order_qty`（1 股）验证

---

## 12. 异常处理

> ⚠️ **状态：部分实现**。已实现：下单失败记 `status=failed`（`engine.py:176`）、不连锁下单（`detect_crossing` 取最近穿越）、重复信号去重（`should_execute`）、进程重启从 `grid_state` 恢复（`get_state`）。未实现：**部分成交处理**（代码无 `partial` 分支，成交一律按全额即时成交处理）、**富途 API 限频器**（代码中无最小下单间隔/限频逻辑）。断线重连依赖富途 SDK 内置、代码中无显式重连与重订阅逻辑。

| 场景 | 处理 |
|------|------|
| OpenD 断线 | 自动重连（富途 SDK 内置），重连后重新订阅 |
| 下单失败 | 记录 `status=failed`，不影响后续信号 |
| 部分成交 | 记录 `status=partial`，按实际成交数量更新持仓 |
| 进程意外退出 | 状态已持久化到 SQLite，重启后从 grid_state 恢复 |
| 价格跳空穿越多条网格线 | 只触发最近穿越的那一条（避免连锁下单） |
| 网络延迟导致重复信号 | 通过 grid_status 状态去重（bought 层不重复买入） |
| 富途 API 限频 | 下单间隔最小 200ms（内置限频器） |

---

## 13. 日志与监控

### 13.1 日志

```python
import logging

logger = logging.getLogger("grid_trader")

# 关键事件日志
logger.info(f"[SIGNAL] {code} price={price} crossed grid_level={level} → {direction}")
logger.info(f"[ORDER] {direction} {qty}@{price} order_id={oid}")
logger.info(f"[FILL] order_id={oid} filled {fill_qty}@{fill_price} pnl={pnl}")
logger.warning(f"[RISK] Daily loss limit reached: ${daily_pnl}")
logger.error(f"[ERROR] Place order failed: {err}")
```

### 13.2 日志文件

> ⚠️ **状态：设计稿，代码中未实现**（截至 2026-10-12 未找到网格日志的文件 handler/按日轮转逻辑）。实际 `grid-start` 仅调用 `logging.basicConfig(...)` 输出到控制台（`cli.py:498-501`），不写文件、不轮转。

```
data/logs/grid_trader_2026-05-06.log
```

按日轮转，保留 30 天。

---

## 14. 性能考量

| 指标 | 要求 | 说明 |
|------|------|------|
| 行情延迟 | < 100ms | 富途推送本地延迟极低 |
| 决策延迟 | < 10ms | 纯内存计算（比较 + 查状态） |
| 下单延迟 | < 500ms | 含网络往返 |
| 内存占用 | < 50MB | 状态量极小 |
| CPU 占用 | < 5% | 事件驱动，闲时无消耗 |

---

## 15. 实现优先级

| 阶段 | 范围 | 验收标准 |
|------|------|---------|
| **P0** | 建表 + 网格计算 + 行情订阅 + 模拟盘下单 | GLD 模拟盘跑通一个完整买卖循环 |
| **P1** | 风控 + 状态持久化 + 断线恢复 | 进程重启后状态不丢失 |
| **P2** | API 端点 + 实盘切换 | 可通过 API 查看状态，切实盘 |
| **P3** | 日志 + 监控 + 多配置 | 可同时运行多组配置（不同标的） |

---

## 16. 验收标准（P0）

- [ ] `trader-analysis grid-create --code US.GLD --upper 260 --lower 240 --grid-count 10 --order-qty 10` 成功创建配置
- [ ] `trader-analysis grid-start 1` 启动后成功订阅 GLD 实时行情
- [ ] 价格下穿网格线时自动在模拟盘买入
- [ ] 价格上穿网格线时自动在模拟盘卖出
- [ ] 交易记录写入 `grid_orders` 表
- [ ] `trader-analysis grid-status 1` 正确显示持仓和盈亏
- [ ] 非交易时段不下单
- [ ] `trader-analysis grid-stop 1` 正常停止并撤销挂单
- [ ] 持仓达到 `max_position` 后不再买入

---

## 17. GLD 参数参考

GLD（SPDR Gold Shares）当前特征：
- 价格区间：约 $230-$260（2026 年）
- 日内波动：约 $1-3（0.5%-1.2%）
- 成交量充足，流动性好
- 无财报事件风险

**建议初始参数：**

| 参数 | 值 | 理由 |
|------|-----|------|
| upper | 260 | 近期阻力位上方 |
| lower | 240 | 近期支撑位下方 |
| grid_count | 10 | 间距 $2，匹配日内波动 |
| order_qty | 10 | 每格 $2400-$2600，总仓位 $24k-$26k |
| max_position | 100 | 最大 $26k 市值 |
| daily_loss_limit | -200 | 模拟盘先设宽松点 |

> 以上为模拟盘测试参数，实盘前需根据实际账户资金调整。

---

## 实现现状核对表

> 核对时间：2026-10-12。✅ 已实现 / ⚠️ 部分实现或与文档不符 / ❌ 代码中未找到。

| 章节 | 设计内容 | 代码现状 | 对应代码位置 / 说明 |
|------|---------|---------|-------------------|
| §1.3 | 独立进程、`grid-start` 启动、盘中限定 | ✅ | `cli.py:491`；时段判定 `risk_control.py:14` |
| §2.1 | 架构图含 `StateManager` 类 | ⚠️ | 无 `StateManager` 类，实为模块级函数 `state_manager.py` |
| §3.1 | 表 `grid_config` DDL | ✅ | `state_manager.py:14-32` |
| §3.2 | 表 `grid_orders` DDL / status 枚举 | ⚠️ | 表结构一致；实际写入 `submitted`/`failed`/`filled`，未用 `partial`/`cancelled`，`engine.py:176` |
| §3.3 | 表 `grid_state` DDL | ✅ | `state_manager.py:56-66` |
| §4.1 | `calculate_grid_lines` 网格线计算 | ⚠️ | 存在（`strategy.py:8`），参数名 `cfg`，返回值 `round(...,4)` |
| §4.2 | `on_price_update` 信号触发 | ⚠️ | 实为 `detect_crossing`（`strategy.py:18`），取「最近穿越线」 |
| §4.3 | `decide_action` 网格状态决策 | ⚠️ | 实为 `should_execute -> bool`（`strategy.py:45`） |
| §4.4 | 决策流程（风控→状态）顺序 | ⚠️ | 代码为「状态→风控」（`engine.py:144-153`） |
| §5.1 | 富途接口清单（含撤单/持仓查询/订单回调） | ⚠️ | 仅 subscribe/handler/trade/place_order；`cancel_order`、`position_list_query`、`TradeOrderHandlerBase` 未用 |
| §5.2 | 环境切换建连写法 | ⚠️ | `filter_trdmarket=TrdMarket.US`，`trd_env` 在下单时传（`engine.py:62`、`executor.py:28`） |
| §5.3 | 行情订阅 handler 写法 | ⚠️ | 工厂闭包写法 `create_quote_handler`（`quote_handler.py:10`） |
| §5.4 | `place_grid_order` 签名/异常 | ⚠️ | 多 `env` 参数，失败返回 `None`，无 `OrderError`（`executor.py:10`） |
| §5.5 | 订单状态回调 `GridOrderHandler` | ❌ | 无 `order_handler.py`/`on_order_update` |
| §6.1 | 风控规则（含收盘前平仓） | ⚠️ | 4 项已实现（`risk_control.py:26-46`）；尾盘平仓未实现；熔断不置 `paused` |
| §6.2 | `is_trading_hours` 时段控制 | ✅ | `risk_control.py:14`（参数名 `cfg`） |
| §6.3 | `calculate_pnl` 盈亏计算 | ⚠️ | 无独立函数，内联于 `engine.py:194-215` |
| §7.1 | 启动流程（含同步持仓） | ⚠️ | 已实现；步骤 4「同步持仓」未实现 |
| §7.2 | 停止流程（含撤单） | ⚠️ | 已实现；步骤 2「撤销挂单」未实现（`engine.py:99`） |
| §7.3 | 每日重置 daily_reset | ⚠️ | 函数存在（`state_manager.py:212`）但无调用，未自动触发 |
| §8.1 | CLI grid-create/start/stop/status | ✅ | `cli.py:452`/`491`/`521`/`914` |
| §9.1 | `GET /api/grid/status` | ⚠️ | 已实现（`api_server.py:538`），多返回 `max_position`、`grid_lines` |
| §9.2 | `GET /api/grid/orders` | ⚠️ | 已实现（`api_server.py:579`），`total` 为返回条数而非库内总数 |
| §9.3 | `/api/grid/config(s)` 增删改查 | ❌ | 未找到相关路由 |
| §10.1 | 模块文件清单 | ⚠️ | 缺 `order_handler.py` |
| §10.2 | 改动 `storage.py` 建 3 张表 | ⚠️ | DDL 实为 `grid_trader/state_manager.py` |
| §11 | 模拟盘/实盘切换 + 二次确认 | ✅ | `engine.py:56-66`、`cli.py:512-515` |
| §12 | 异常处理（部分成交/限频器/重连） | ⚠️ | `partial` 分支、限频器、显式重连未实现 |
| §13.2 | 日志文件按日轮转保留 30 天 | ❌ | 仅 `logging.basicConfig` 输出控制台（`cli.py:498`） |

**统计**：✅ 6 条 ｜ ⚠️ 20 条 ｜ ❌ 3 条（共 29 条）。
