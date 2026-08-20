# 标的池管理模块 技术设计文档

> 最后更新：2026-08-20 | 版本：v1.1 | 状态：P0+P1+P2 已实现

---

## 1. 概述

### 1.1 目标

将标的池从静态 JSON 文件迁移到 SQLite 持久化存储，提供 RESTful CRUD API，并对接富途条件选股接口实现新股票基础信息自动填充。

### 1.2 现状问题

| 问题 | 影响 |
|------|------|
| `data/watchlist.json` 手动编辑 | 易出错、需重启服务 |
| 无版本管理 | 字段修改无历史记录 |
| 无基本面数据字段 | 估值信息散落在其他地方 |
| 新增股票需手动查信息 | 效率低 |

### 1.3 设计原则

- **纯 API**：前端独立项目，本模块只提供 RESTful 接口
- **向后兼容**：迁移期间保留 `config.WATCHLIST` 接口，从 DB 读取
- **字段分层**：静态字段（自动填充/不可改）vs 动态字段（用户手动维护）
- **简单对接**：富途选股只做基础信息填充，不做全功能筛选器

### 1.4 标的池加入规则

> 本节定义「一只股票能否进入标的池」的业务标准。投资哲学遵循巴菲特原则：**不懂不做、不做空、不借钱加杠杆**。

#### 1.4.1 纳入标准（需同时满足）

| 维度 | 规则 | 说明 |
|------|------|------|
| **市场** | 美股（US）为主，港股（HK）少量 | 仅纳入富途 OpenD 可获取行情的市场 |
| **市值** | 大市值龙头为主，目标 ≥ $50B | 避免小盘股流动性差、波动剧烈、易操纵 |
| **行业覆盖** | 覆盖主要行业板块，每板块选龙头 1~3 只 | 26 个板块：MAG7、半导体、金融、医疗、消费、能源、工业、科技、云、AI 基建等 |
| **可估值** | 有晨星公允价值或分析师目标价 | 否则无法计算折价率，无法纳入低估做多筛选 |
| **数据可得** | 富途 OpenD 能稳定拉取日线/周线/4H K 线 | 数据是评分、道氏趋势、信号检测的前提 |

#### 1.4.2 排除项（禁止纳入）

| 类型 | 原因 |
|------|------|
| **杠杆 ETF**（2x/3x，如 SOXL、KORU、TQQQ） | 与对应正股 ETF 重复；杠杆有损耗，不符合「不借钱加杠杆」 |
| **反向 / 做空 ETF**（如 SQQQ、SOXS） | 违背「不做空」原则 |
| **重复的行业 ETF** | 同一板块只保留正股 ETF 或龙头个股，二者取一 |
| **无晨星/分析师覆盖的小盘股** | 无法估值，超出「不懂不做」的能力圈 |

> 2026-08-20 据此规则清理：剔除 7 只杠杆/重复 ETF（YINN、SOXL、KORU、HK.07709、GDXU、EUV、FOTO），标的池由 203 → 196 只。

#### 1.4.3 动态维护

- **管理方式**：通过 RESTful API 增删改查（`POST/PATCH/DELETE /api/watchlist`），不再编辑 JSON 文件
- **新增流程**：`POST /api/watchlist` → 富途自动填充名称/行业 → 跑 `init` 拉历史 K 线 → `score`/`scan-signals` 纳入评分与信号
- **删除流程**：`DELETE /api/watchlist/{code}` → 仅移除标的池记录，不删除 `kline_indicators`/`score_results` 历史数据
- **config.WATCHLIST 联动**：`_WatchlistProxy` 动态从 DB 读取，CRUD 后 CLI 命令（init/update/score/scan-signals）自动使用最新列表

---

## 2. 数据模型

### 2.1 新表：`watchlist`

```sql
CREATE TABLE IF NOT EXISTS watchlist (
    -- 主键
    code            TEXT PRIMARY KEY,          -- Futu 格式: US.AAPL, HK.07709

    -- 基础信息（新增时自动填充，不可修改）
    ticker          TEXT NOT NULL,             -- 纯 ticker: AAPL
    name            TEXT NOT NULL,             -- 公司名称: Apple Inc.
    market          TEXT NOT NULL,             -- US / HK
    sector          TEXT,                      -- 行业板块: Technology
    industry        TEXT,                      -- 细分行业: Consumer Electronics
    listing_date    TEXT,                      -- 上市日期

    -- 分类与状态（用户可改）
    category        TEXT NOT NULL DEFAULT '',  -- 用户自定义分类: mag7, semiconductor...
    status          TEXT NOT NULL DEFAULT 'watching',  -- watching / holding / exited
    tags            TEXT DEFAULT '[]',         -- JSON 数组: ["AI", "chip"]

    -- 用户估值判断（可改，反映对未来的预期）
    target_price    REAL,                      -- 用户目标价
    stop_loss       REAL,                      -- 用户止损价
    analyst_target_mean   REAL,               -- 分析师平均目标价（手动填入）
    morningstar_fair_value REAL,              -- 晨星公允价格（手动填入）

    -- 基本面数据（可改，因为未来业绩预期会变）
    forward_pe      REAL,                      -- 预期市盈率
    forward_eps     REAL,                      -- 预期每股收益
    peg_ratio       REAL,                      -- PEG 比率
    revenue_growth  REAL,                      -- 营收增长率 (小数: 0.25 = 25%)
    earnings_growth REAL,                      -- 盈利增长率
    profit_margin   REAL,                      -- 净利润率
    roe             REAL,                      -- 净资产收益率
    debt_to_equity  REAL,                      -- 资产负债率

    -- 静态基本面快照（不可改，反映当前事实，由系统写入）
    trailing_pe     REAL,                      -- 静态市盈率
    market_cap      REAL,                      -- 市值
    current_price   REAL,                      -- 最近价格（快照）
    dividend_yield  REAL,                      -- 股息率
    beta            REAL,                      -- Beta 系数

    -- 备注
    thesis          TEXT DEFAULT '',           -- 投资逻辑
    notes           TEXT DEFAULT '',           -- 备注（高频编辑）

    -- 时间戳
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_watchlist_category ON watchlist(category);
CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist(status);
CREATE INDEX IF NOT EXISTS idx_watchlist_market ON watchlist(market);
```

### 2.2 字段分类总览

| 分类 | 字段 | 可编辑 | 来源 |
|------|------|--------|------|
| **身份标识** | code, ticker, name, market | ❌ | 富途自动填充 |
| **行业信息** | sector, industry, listing_date | ❌ | 富途自动填充 |
| **用户分类** | category, status, tags | ✅ | 用户手动 |
| **用户估值** | target_price, stop_loss, analyst_target_mean, morningstar_fair_value | ✅ | 用户手动 |
| **前瞻基本面** | forward_pe, forward_eps, peg_ratio, revenue_growth, earnings_growth, profit_margin, roe, debt_to_equity | ✅ | 用户手动 / 基本面模块写入 |
| **静态快照** | trailing_pe, market_cap, current_price, dividend_yield, beta | ❌ | 系统定期更新 |
| **备注** | thesis, notes | ✅ | 用户手动 |

### 2.3 数据迁移

从现有 `data/watchlist.json` 一次性导入：

```python
# 迁移映射
json_field → db_field:
  ticker     → ticker
  name       → name
  market     → market
  category   → category
  thesis     → thesis
  target_price → target_price
  stop_loss  → stop_loss
  status     → status
  tags       → tags (JSON string)
  notes      → notes

# code 字段由 market + ticker 生成: f"{market}.{ticker}"
# sector, industry 等字段初次为空，后续通过富途 API 补充
```

提供 CLI 命令执行迁移：
```bash
trader-analysis migrate-watchlist        # JSON → SQLite 一次性迁移
trader-analysis migrate-watchlist --dry   # 预览，不写入
```

---

## 3. API 设计

### 3.1 CRUD 端点

#### 3.1.1 查询标的列表

```
GET /api/watchlist
```

**Query Parameters:**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `category` | str | 否 | — | 按分类过滤 |
| `status` | str | 否 | — | 按状态过滤: watching/holding/exited |
| `market` | str | 否 | — | 按市场过滤: US/HK |
| `search` | str | 否 | — | 模糊搜索 ticker/name/notes |

**Response 200:**

```json
{
  "total": 40,
  "categories": {
    "mag7": "MAG7",
    "semiconductor": "强势半导体"
  },
  "watchlist": [
    {
      "code": "US.AAPL",
      "ticker": "AAPL",
      "name": "Apple Inc.",
      "market": "US",
      "sector": "Technology",
      "industry": "Consumer Electronics",
      "category": "mag7",
      "status": "watching",
      "tags": ["AI", "chip"],
      "target_price": 250.0,
      "stop_loss": 180.0,
      "analyst_target_mean": 235.0,
      "morningstar_fair_value": 210.0,
      "forward_pe": 28.5,
      "forward_eps": 7.80,
      "trailing_pe": 32.1,
      "market_cap": 3200000000000,
      "current_price": 220.50,
      "thesis": "AI on device + Services 增长",
      "notes": "Q2 财报后重新评估",
      "has_data": true,
      "created_at": "2026-04-13T00:00:00",
      "updated_at": "2026-05-05T10:30:00"
    }
  ]
}
```

> 注：`has_data` 字段保留，表示该股票在 `kline_indicators` 中是否有数据。

---

#### 3.1.2 查询单只标的

```
GET /api/watchlist/{code}
```

**Path Parameter:** `code` — Futu 格式代码（如 `US.AAPL`）

**Response 200:** 单个标的完整信息（同列表中的单条结构）

**Response 200 (不存在):**
```json
{"data": null, "message": "Stock US.XXXX not found in watchlist"}
```

---

#### 3.1.3 新增标的

```
POST /api/watchlist
```

**Request Body:**

```json
{
  "code": "US.SNDK",
  "category": "storage",
  "thesis": "存储周期底部",
  "notes": "",
  "tags": ["storage", "cyclical"],
  "target_price": 220.0,
  "stop_loss": 150.0
}
```

**必填字段:** `code`（Futu 格式）

**处理流程:**
1. 解析 code → market + ticker
2. 调用富途 API 获取基础信息（name, sector, industry, listing_date）
3. 若富途获取失败，name 回退为 ticker，其他字段留空
4. 写入 SQLite
5. 返回完整记录

**Response 201:**
```json
{
  "message": "Stock US.SNDK added to watchlist",
  "data": { ... }
}
```

**Response 409 (已存在):**
```json
{"data": null, "message": "Stock US.SNDK already exists in watchlist"}
```

---

#### 3.1.4 修改标的

```
PATCH /api/watchlist/{code}
```

**Request Body (部分更新，只传需要改的字段):**

```json
{
  "notes": "2026Q2 下调 EPS 预期",
  "forward_pe": 25.0,
  "forward_eps": 6.50,
  "analyst_target_mean": 200.0,
  "status": "holding"
}
```

**可修改字段白名单:**

```python
EDITABLE_FIELDS = [
    # 用户分类
    "category", "status", "tags",
    # 用户估值
    "target_price", "stop_loss",
    "analyst_target_mean", "morningstar_fair_value",
    # 前瞻基本面
    "forward_pe", "forward_eps", "peg_ratio",
    "revenue_growth", "earnings_growth",
    "profit_margin", "roe", "debt_to_equity",
    # 备注
    "thesis", "notes",
]
```

**不可修改字段（请求中包含则忽略或报错）:**

```python
READONLY_FIELDS = [
    "code", "ticker", "name", "market",
    "sector", "industry", "listing_date",
    "trailing_pe", "market_cap", "current_price",
    "dividend_yield", "beta",
    "created_at",
]
```

**Response 200:**
```json
{
  "message": "Stock US.SNDK updated",
  "data": { ... },
  "updated_fields": ["notes", "forward_pe", "forward_eps"]
}
```

**Response 400 (尝试改只读字段):**
```json
{"data": null, "message": "Fields not editable: trailing_pe, market_cap"}
```

---

#### 3.1.5 删除标的

```
DELETE /api/watchlist/{code}
```

**Response 200:**
```json
{"message": "Stock US.SNDK removed from watchlist"}
```

> 注：仅删除 watchlist 记录，不删除 `kline_indicators` / `score_results` 中的历史数据。

---

#### 3.1.6 批量新增

```
POST /api/watchlist/batch
```

**Request Body:**
```json
{
  "codes": ["US.SNDK", "US.MU", "US.WDC"],
  "category": "storage",
  "tags": ["storage"]
}
```

**Response 200:**
```json
{
  "message": "3 stocks added, 0 skipped",
  "added": ["US.SNDK", "US.MU", "US.WDC"],
  "skipped": []
}
```

---

### 3.2 富途选股对接端点

#### 3.2.1 条件选股查询

```
GET /api/stock-filter/search
```

**Query Parameters:**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `market` | str | 否 | `US` | 市场: US / HK |
| `min_market_cap` | float | 否 | — | 最小市值（亿美元） |
| `max_pe` | float | 否 | — | 最大市盈率 |
| `min_price` | float | 否 | — | 最低股价 |
| `sector` | str | 否 | — | 行业板块 |

> 只做最基础的筛选条件，目的是方便查找股票并填充信息，不是全功能选股器。

**Response 200:**

```json
{
  "total": 15,
  "results": [
    {
      "code": "US.SNDK",
      "ticker": "SNDK",
      "name": "Sandisk Corp",
      "market": "US",
      "sector": "Technology",
      "industry": "Data Storage",
      "market_cap": 22000000000,
      "trailing_pe": 18.5,
      "current_price": 185.30,
      "in_watchlist": false
    }
  ]
}
```

> `in_watchlist` 字段标记该股票是否已在标的池中。

**依赖:** 需要富途 OpenD 在线连接。

---

#### 3.2.2 单股信息查询（填充辅助）

```
GET /api/stock-filter/info?code=US.SNDK
```

**用途:** 新增标的前，先查询该股票的基础信息预览。

**Response 200:**
```json
{
  "code": "US.SNDK",
  "ticker": "SNDK",
  "name": "Sandisk Corp",
  "market": "US",
  "sector": "Technology",
  "industry": "Data Storage",
  "listing_date": "2004-12-15",
  "market_cap": 22000000000,
  "trailing_pe": 18.5,
  "current_price": 185.30,
  "dividend_yield": 0.012,
  "beta": 1.35
}
```

> 这些数据会在 `POST /api/watchlist` 时自动写入静态字段。

---

### 3.3 静态快照刷新端点

```
POST /api/watchlist/refresh-snapshot
```

**Query Parameters:**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `code` | str | 否 | — | 指定刷新单只，不传则刷新全部 |

**用途:** 定期刷新 `trailing_pe`, `market_cap`, `current_price`, `dividend_yield`, `beta` 这些"当前事实"字段。

**Response 200:**
```json
{
  "message": "Refreshed 40 stocks",
  "updated": 38,
  "failed": ["US.XXXX", "HK.00000"]
}
```

**触发方式:**
- 手动调用 API
- CLI 命令: `trader-analysis refresh-snapshot`
- 可选：挂载到 `daily_update` 流程末尾自动执行

---

## 4. CLI 设计

### 4.1 新增命令

```python
@app.command()
def migrate_watchlist(
    dry: bool = typer.Option(False, help="预览模式，不实际写入"),
):
    """从 watchlist.json 迁移到 SQLite"""

@app.command()
def refresh_snapshot(
    codes: list[str] = typer.Option(None, help="指定代码，不传则全部刷新"),
):
    """刷新标的池静态快照字段"""
```

### 4.2 现有命令适配

所有使用 `config.WATCHLIST` 的命令保持接口不变，内部改为从 DB 读取：

```python
# config.py 改造
def get_watchlist() -> list[str]:
    """从 SQLite 读取活跃标的列表（status != 'exited'）"""
    ...

# 兼容：WATCHLIST = get_watchlist() 仍可用
# 但改为函数调用，支持动态更新
```

---

## 5. 富途 API 对接细节

### 5.1 使用的富途接口

| 接口 | 用途 | 备注 |
|------|------|------|
| `get_stock_basicinfo()` | 获取股票基础信息（名称、行业、上市日期） | 不消耗行情额度 |
| `get_market_snapshot()` | 获取实时快照（价格、市值、PE） | 消耗额度 |
| `get_stock_filter()` | 条件选股 | 按条件筛选 |

### 5.2 接口封装

```python
# stock_info_fetcher.py (新文件)

from futu import OpenQuoteContext, StockFilter, Market, SortDir

def fetch_stock_info(code: str) -> dict | None:
    """获取单只股票基础信息，用于新增标的时自动填充"""
    # 返回: {name, sector, industry, listing_date, market_cap, trailing_pe, ...}
    ...

def search_stocks(
    market: str = "US",
    min_market_cap: float | None = None,
    max_pe: float | None = None,
    sector: str | None = None,
) -> list[dict]:
    """条件选股，返回候选列表"""
    ...
```

### 5.3 富途连接要求

- 需要 OpenD 在线（与现有 K 线获取共用连接）
- 选股/查询接口无额度限制（basicinfo 免费）
- snapshot 有日频限制，refresh-snapshot 建议每日仅执行一次

### 5.4 降级策略

富途 OpenD 不在线时：
- `POST /api/watchlist` — 仍可新增，但 name 回退为 ticker，sector/industry 为空
- `GET /api/stock-filter/search` — 返回 503：`{"data": null, "message": "Futu OpenD not connected"}`
- 其他 CRUD 操作不受影响（纯 SQLite 读写）

---

## 6. 与基本面模块的协同

### 6.1 写入路径

```
基本面分析模块（fundamental_fetcher）
    ↓ 计算完成后
调用 watchlist storage 层
    ↓ 更新字段
watchlist 表的 forward_pe, forward_eps, peg_ratio 等可编辑字段
```

### 6.2 接口约定

基本面模块提供一个写入函数：

```python
def sync_fundamental_to_watchlist(code: str, data: dict) -> None:
    """将基本面分析结果同步到 watchlist 表的对应字段"""
    # 只更新 EDITABLE_FIELDS 中的基本面字段
    # 不覆盖用户手动修改过的值（可选：加 force 参数）
    ...
```

### 6.3 冲突处理

用户手动修改 vs 系统自动写入的优先级：

| 场景 | 策略 |
|------|------|
| 用户手动改了 forward_pe | 系统不覆盖（除非用户主动触发刷新） |
| 用户从未填过 forward_pe | 系统可自动写入 |
| refresh-snapshot 刷新静态字段 | 无条件覆盖（静态字段反映事实） |

实现方式：可编辑字段加 `user_modified` 标记，或比较 `updated_at` 时间戳判断。

> v1 简化方案：基本面模块写入时无条件覆盖可编辑字段，用户如需保留自己的值则手动回改。

---

## 7. 模块结构

### 7.1 新增文件

```
src/trader_analysis/futu_strategy/
├── watchlist_storage.py      # watchlist 表 CRUD
├── stock_info_fetcher.py     # 富途基础信息/选股接口封装
└── ...
```

### 7.2 修改文件

```
src/trader_analysis/futu_strategy/
├── config.py                 # WATCHLIST 改为从 DB 读取
├── api_server.py             # 新增 CRUD + stock-filter 路由
├── storage.py                # 新增 watchlist 建表语句
└── ...

src/trader_analysis/
├── cli.py                    # 新增 migrate-watchlist, refresh-snapshot 命令
└── ...
```

---

## 8. 兼容性与迁移策略

### 8.1 迁移步骤

```
1. 新建 watchlist 表（storage.py init_db 中添加）
2. 运行 migrate-watchlist 命令导入 JSON 数据
3. config.py 中 WATCHLIST 改为 get_watchlist() 动态读取
4. 验证所有依赖模块正常（init/update/score/run）
5. watchlist.json 保留作为备份，不再作为数据源
```

### 8.2 向后兼容

| 模块 | 影响 | 适配方式 |
|------|------|---------|
| `init_history.py` | 使用 `config.WATCHLIST` | 无需改动（WATCHLIST 接口不变） |
| `daily_update.py` | 同上 | 无需改动 |
| `scorer.py` | 同上 | 无需改动 |
| `runner.py` | 同上 | 无需改动 |
| `api_server.py:/api/watchlist` | 当前返回 `config.WATCHLIST_DETAIL` | 改为从 DB 查询 |

### 8.3 categories 管理

现有 `watchlist.json` 中的 `categories` 字典迁移方案：
- **v1 简化方案：** categories 仍保留在 config.py 中作为常量（变动极低频）
- **v2 扩展：** 可加 `watchlist_categories` 表

---

## 9. 边界情况

| 场景 | 处理 |
|------|------|
| 新增已存在的 code | 返回 409 Conflict |
| 删除不存在的 code | 返回 200（幂等） |
| PATCH 不存在的 code | 返回 `{"data": null, "message": "..."}` |
| PATCH 包含只读字段 | 返回 400，列出不可编辑的字段名 |
| 富途 OpenD 离线时新增 | 降级：name=ticker，行业字段空 |
| 富途 OpenD 离线时选股 | 返回 503 |
| 批量新增部分失败 | 返回成功/跳过列表，不全量回滚 |
| tags 格式错误 | 期望 JSON 数组，非法格式返回 422 |
| 数值字段传入字符串 | FastAPI Pydantic 校验，返回 422 |

---

## 10. 性能考量

| 操作 | 数据量 | 预期耗时 |
|------|--------|---------|
| 查询列表（40 股） | 40 行 | < 10ms |
| 单条 CRUD | 1 行 | < 5ms |
| refresh-snapshot（40 股） | 40 次富途调用 | ~20-40s（含限频） |
| 条件选股 | 富途返回最多 200 条 | 1-3s |
| migrate-watchlist | 40 条插入 | < 100ms |

---

## 11. 实现优先级

| 阶段 | 范围 | 验收标准 |
|------|------|---------|
| **P0** | 建表 + 迁移 + 基础 CRUD API | GET/POST/PATCH/DELETE 可用，现有模块不受影响 |
| **P1** | 富途信息填充 + stock-filter | 新增标的时自动填充名称/行业 |
| **P2** | refresh-snapshot + CLI | 静态字段定期刷新 |
| **P3** | 基本面模块写入协同 | fundamental 模块可同步数据到 watchlist |

---

## 12. 验收标准（P0）

- [ ] `trader-analysis migrate-watchlist` 成功导入 40 条记录
- [ ] `GET /api/watchlist` 返回结构与现有兼容（前端无感切换）
- [ ] `POST /api/watchlist` 可新增标的（OpenD 离线时降级正常）
- [ ] `PATCH /api/watchlist/US.AAPL` 可修改 notes/forward_pe 等
- [ ] `PATCH` 尝试修改 trailing_pe/market_cap 时返回 400
- [ ] `DELETE /api/watchlist/US.XXXX` 删除后不影响历史评分数据
- [ ] `trader-analysis score` / `update` / `run` 功能不受影响
- [ ] 单条 CRUD 响应时间 < 50ms
