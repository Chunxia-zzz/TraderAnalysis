# Implementation Plan: 市场温度按指数拆分（SPY / QQQ 独立计算与展示）

**Branch**: `003-split-market-temperature` | **Date**: 2026-11-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-split-market-temperature/spec.md`

## Summary

把「SPY + QQQ 每维各 50% 的合并温度」改为「两个指数各自一套三维温度」，**合并口径退役但历史冻结保留**。

四处关键改动：

1. **计算端**：复用已有的单资产三维框架（`_score_asset_daily/_weekly/_price_position`），为 SPY / QQQ 各配一份阈值（**数值相同**，满足 FR-002 共用一套），产出两个独立结果
2. **存储端**：新增 `market_temp_split(date, code)` 复合主键表；`market_score` / `market_score_detail` 停止写入、原样冻结
3. **接口端**：`/api/market-temperature` 由单对象改为 `indexes[] + spread`；历史端点改为返回两条序列 + 温差序列，起点不早于 2025-01-01
4. **消费端**：个股评分的「恐慌加成」改由 `(SPY + QQQ) / 2` 供给，保证 `total_score` 与变更前一致（FR-016）；前端温度页拆成两张卡 + 温差趋势

## Technical Context

**Language/Version**: Python 3.10+ / TypeScript(Vue 3 SFC)

**Primary Dependencies**: FastAPI、pandas；Vue 3 + Vite + Ant Design Vue + ECharts（温度页现用 echarts）

**Storage**: SQLite `data/indicators.db`；**新增一张表**，不改既有表结构

**Testing**: pytest；前端人工走查 + 控制台检查

**Target Platform**: 本地开发（Windows）+ 线上 Linux（systemd + nginx）

**Project Type**: web-service + SPA（前端为独立仓库 `F:\TraderAnalysisFrontend`）

**Constraints**:
- 不得对 `market_score` / `market_score_detail` 执行 `DELETE` / `UPDATE`
- 同一数据日两指数的温度之和除以 2 必须等于旧合并值（容差 ±0.5）
- 两个指数共用同一套阈值，**不得**为 QQQ 单独放宽
- 前后端是两个仓库，接口契约以后端为准，先改后端
- 温差历史**只回算 2025-01-01 起**，更早不补算

**Scale/Scope**: 后端 5 个文件（scorer / storage / api_server / cli / runner）+ 1 个新测试文件；前端 2 个文件；文档 6 处

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 判定 | 结论 |
|---|---|---|
| **I. 两套信号体系不可合并** | 只动市场温度与指数维度，不触碰 `total_score` 的六因子构成，也不触碰 `livermore_signal_log`。恐慌加成的**输入值**保持等价（FR-016），因此 `total_score` 与利弗莫尔的分工与边界不变。 | ✅ 通过 |
| **II. 口径是事实，不是可调参数** | 方向不变（高分=恐慌=加仓）；仍是**三维 50/35/15**，未新增维度、未复活已废弃维度。两个指数各有一套仓位映射，映射函数本身不改，**单调递增性质保持**。跨口径红线：合并值与拆分值不可混用，文档必须显式说明。 | ✅ 通过（须在文档标注「合并/拆分不可混用」） |
| **III. 术语精确，混称即缺陷** | 新增术语「指数温度」「温差」，必须与「市场温度」「账户温度」区分：文档中一律写「SPY 温度 / QQQ 温度」，不写「大盘温度」指代单个指数。`spread` 的符号语义（SPY − QQQ）必须在代码注释、字段名、文案、文档四处一致。 | ⚠️ 需逐处核对，禁止出现「大盘温度 79.4」这类混称 |
| **IV. 单一真相源，派生物不入库** | 阈值只在 `_INDEX_CONFIGS` 一处定义；前端不复制映射表。新表是计算产物，DB 仍不入库；不新增派生文件。 | ✅ 通过 |
| **V. 文档与代码必须同时为真** | `api.md`（两个端点结构变更）、`modules/market-temperature.md`（口径与公式）、`storage.md`（新表）、`README.md`、`CHANGELOG.md` 全部同步。历史段落不删改，加勘误行。 | ⚠️ 重点执行 |
| **VI. 规范先行** | 本 spec / plan / tasks 先于实现；属「改计算口径 + 改 API 契约 + 改数据模型」，三项都命中必须写规范的条件。 | ✅ 通过 |

**Constitution 连带影响**：

1. §三 质量门写「当前 95 项」，而 `specs/002/plan.md` 写「当前 97 项」——**两份已互相矛盾**。本次实现后以 `pytest -q` 实测数字为准统一校正，并在 CHANGELOG 记一行说明是「校正既有不一致」，不是本次增删导致。
2. 原则 II 的判定句提到 `docs/modules/market-temperature.md §4.0 的口径快照与代码一致`。拆分后该节必须重写，否则判定失效。

## 技术方案

### 1. 计算端（`market_scorer.py`）

复用已有单资产框架，不再新写一套算法：

```python
_INDEX_CONFIGS = {
    "SPY": {"label": "标普 500",    "code": "US.SPY", "code_weekly": "US.SPY",
            "ath_drawdown_zero": 0.15, "ma200_range": 0.15},
    "QQQ": {"label": "纳斯达克 100", "code": "US.QQQ", "code_weekly": "US.QQQ",
            "ath_drawdown_zero": 0.15, "ma200_range": 0.15},
}
```

- 两个配置的阈值**故意写成相同的值**：满足 FR-002「共用一套」，将来要改也只改这两行，并且改动会在 review 中显式可见
- `compute_index_temperature(key) -> dict`：调 `_score_asset_daily` / `_score_asset_weekly` / `_score_asset_price_position`，加权 50/35/15，再走 `_map_status` / `_map_position`
- `compute_index_temperature_history(key, start_date)`：按交易日滑窗切片，周线用 `market_clock.filter_week_closed` 防前视，与现有 `compute_asset_temperature_history` 同构
- `compute_temperature_spread(spy, qqq) -> float`：`round(spy - qqq, 1)`

**删除的合并路径**（避免两套口径长期并存）：

- `_score_daily_tech` / `_score_weekly_tech` / `_score_price_position`（合并版，只在合并路径用）
- `_compute_score` / `calculate_market_temperature` / `backfill_market_temperature`
- 删除前用 `grep -rn` 确认无其它调用点；`scores` 相关函数不在此列

### 2. 存储端（`storage.py`）

新增（`init_db` 内 `CREATE TABLE IF NOT EXISTS`，纯增量、不动既有表）：

```sql
CREATE TABLE IF NOT EXISTS market_temp_split (
  date TEXT NOT NULL,
  code TEXT NOT NULL,                -- US.SPY / US.QQQ
  composite_score REAL NOT NULL,
  target_position_pct REAL,
  extreme_triggered INTEGER DEFAULT 0,
  extreme_level TEXT DEFAULT 'none',
  leverage_tool TEXT DEFAULT 'none',
  market_status TEXT,
  action_suggestion TEXT,
  daily_tech_score REAL,
  weekly_tech_score REAL,
  price_score REAL,
  price REAL,
  daily_rsi REAL,
  weekly_rsi REAL,
  ma200_dev REAL,
  ath_drawdown REAL,
  pos_52w REAL,
  detail_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (date, code)
);
```

- `upsert_market_temp_split(date, code, result)`：`INSERT OR REPLACE`，天然幂等（FR-008）
- `query_latest_market_temp_split()` → 返回某日两条
- `query_market_temp_split_history(start_date, code=None)` → 升序序列
- `query_panic_composite(dates)`：**恐慌加成的唯一读入口** —— 先按日期取 split 表两指数平均，缺失则回落 `market_score`（2025-01-01 以前只有合并值）。这样 FR-016 与历史回算同时成立
- **删除** `upsert_market_score`（写路径退役，留着等于留一条随时能破坏冻结的通道）
- `query_latest_market_score` / `query_market_score_history` 若无调用点则删除；`market_score_detail` 的 join 一并移除

### 3. 接口端（`api_server.py`）

| 端点 | 改动 |
|---|---|
| `GET /api/market-temperature` | 返回 `{date, indexes: [SPY, QQQ], spread: {value, label}, gld_temp, btc_temp}`；不再有顶层 `composite_score` / `target_position_pct` |
| `GET /api/market-temperature/history` | 参数 `days`（默认 465、上限 600）与可选 `start`（默认 2025-01-01，早于该日一律截断）；返回 `{series: [{code, points}], spread: [{date, value}]}` |
| `GET /api/asset-temperature/history` | 不变（GLD/BTC 继续复用） |

`spread.label` 的取值只有两种：`"标普相对更强"`（值 < 0）/ `"纳指相对更强"`（值 > 0），等于 0 时 `"均衡"`。**文案由后端给出**，避免前端各写一套。

### 4. 命令行（`cli.py`）

```bash
trader-analysis temperature                  # 算当日两个指数并写库
trader-analysis temperature --backfill 30    # 回算最近 30 个交易日
trader-analysis temperature --since 2025-01-01   # 一次性迁移，回算到指定日期
```

`--since` 与 `--backfill` 互斥，同时传报错。输出形如：

```
SPY  70.3 偏悲观/积极加仓  仓位 81.6%
QQQ  79.4 偏悲观/积极加仓  仓位 91.6%（轻极端层）
温差 -9.1（标普相对更强）
```

### 5. 恐慌加成（保证 `total_score` 不失血）

- `scorer.calculate_score(market_composite=...)` **签名不变**
- `cli.py:104` 的 `SELECT date, composite_score FROM market_score` 改为 `storage.query_panic_composite()` 返回的 `{date: composite}`（split 平均优先，回落旧表）
- `runner.py:84` 的取最新值改为同一函数取最新日期
- 这样 2025-01-01 之后走 split 平均、之前走旧合并值，**同一日算出的加成与变更前完全一致**

### 6. 前端（独立仓库）

| 文件 | 改动 |
|---|---|
| `src/api/trader.js` | `getMarketTemperature()` 路径不变；新增 `getMarketTemperatureHistory({days, start})` |
| `src/views/MarketTemperature.vue` | 视图切换从 `market / gold / btc` 改为 `spy / qqq / spread / gold / btc`；SPY/QQQ 两张卡复用现有 hero + 维度拆解结构，数据源改为 `data.indexes[i]`；新增温差卡片与温差折线（正负分色）；删除对顶层 `composite_score` / `target_position_pct` 的引用 |

前端不改阈值与文案映射，`getLevel(score)` 继续用本地阈值表（与后端 `_STATUS_LEVELS` 同源，本次不动）。

### 7. 测试（`tests/test_split_market_temperature.py`）

| 用例 | 断言 |
|---|---|
| 单指数三维加权 | 手工构造 DataFrame，`composite == 0.5*daily + 0.35*weekly + 0.15*price` |
| 与旧口径等价 | 2026-11-09 真实库：SPY 70.3 / QQQ 79.4 / 平均 74.85 ≈ 旧值 74.9（容差 0.5） |
| 幂等 | 同一日 upsert 两次，`COUNT(*) == 2` |
| 温差符号 | `spread < 0` 时 label 为「标普相对更强」 |
| 数据不足降级 | 单指数日线为空时返回 `None` 或 `data_insufficient`，不伪造 50 分 |
| 历史起点 | `start=2025-01-01` 的结果首日期 ≥ 该日；更早日期被截断 |
| 恐慌加成连续 | 2025-01-01 之后某日 `query_panic_composite` 的值 == split 两行平均 |

### 8. 文档

| 文件 | 改法 |
|---|---|
| `docs/reference/api.md` | 两个端点的新结构、字段表、示例（示例数值标注虚构）；旧结构加勘误行 |
| `docs/modules/market-temperature.md` | §4.0 口径快照重写：合并 → 双指数；补「温差」定义与符号语义；补「合并值已退役冻结」 |
| `docs/reference/storage.md` | 新增 `market_temp_split` 表说明；`market_score` 标注「冻结、不再写入」 |
| `docs/history/CHANGELOG.md` | 新增条目：为什么拆、为什么冻结旧表、为什么恐慌加成用平均、测试数校正 |
| `README.md` | 温度能力描述同步 |
| `AGENTS.md` / `constitution.md` | 测试数统一为实测值，并说明是校正既有不一致 |

## Project Structure

### Documentation (this feature)

```text
specs/003-split-market-temperature/
├── spec.md
├── plan.md      # 本文件
└── tasks.md
```

### Source Code

```text
src/trader_analysis/
├── cli.py                                   # temperature 命令 + 恐慌加成取数
└── futu_strategy/
    ├── market_scorer.py                     # 双指数计算，删合并路径
    ├── storage.py                           # 新表 + upsert/query + query_panic_composite
    ├── api_server.py                        # 两个端点结构变更
    └── runner.py                            # 恐慌加成取数

tests/test_split_market_temperature.py        # 新增

(F:\TraderAnalysisFrontend)
src/api/trader.js
src/views/MarketTemperature.vue
```

**Structure Decision**: 后端先改（契约以它为准），前端随后跟进；两侧各自提交。历史回算脚本并入 CLI（`--since`），不额外建 `scripts/` 一次性脚本，避免「跑完就忘」的死代码。

## 风险与回滚

| 风险 | 影响 | 处置 |
|---|---|---|
| 恐慌加成失血 | 全池 `total_score` 静默下降，信号池整体位移 | SC-008 抽查 3 日重算比对；实现后用 11-09 全量重算与旧值对比，均值偏差 >0.5 即中止 |
| 误删合并历史 | 不可逆 | 全程不对 `market_score` 执行写操作；实现前 `cp data/indicators.db data/_backup/…-preSplit` |
| 温差符号写反 | 结论完全反向 | 单元测试锁死符号与 label；页面文案由后端给 |
| 前端旧 chunk | 白屏或字段 undefined | 强刷验证；`data.indexes` 缺失时页面给明确空状态而不是崩 |
| 2025 前回算丢加成 | `score --backfill` 回算早年数据分数偏低 | `query_panic_composite` 回落旧表，专门测一条 2024 年日期 |
| 线上旧进程缓存 | 接口仍返回旧结构 | 部署后重启 `trader-api`，抽查 `/api/market-temperature` 顶层无 `composite_score` |

**回滚**：代码 `git revert` 即可；数据侧新表可整表删除（`DROP TABLE market_temp_split`），旧表未动，回滚后 `temperature` 仍能从 2025-01-01 重算。

## Complexity Tracking

| 违反项 | 原因 | 为何可接受 |
|---|---|---|
| 新增一张表（宪法 IV 要求单一真相源） | 旧表以 `date` 为主键，物理上无法容纳两个指数 | 新表是唯一真相源，旧表转为只读历史；不并存写入，不产生双写不一致 |
