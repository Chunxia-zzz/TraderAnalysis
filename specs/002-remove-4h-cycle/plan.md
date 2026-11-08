# Implementation Plan: 移除 4H 周期相关的全部功能与逻辑

**Branch**: `002-remove-4h-cycle` | **Date**: 2026-11-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-remove-4h-cycle/spec.md`

## Summary

把 4H 周期从「拉取 → 计算 → 落库 → API → 前端」整条链路摘掉，**只删代码路径，不动数据库里的行**。
日线 / 周线链路一行逻辑都不改，作为回归基线。

四处关键改动：

1. 采集端只保留 `1d` / `1w`（`daily_update.py`、`config.py`、三条运维脚本）
2. 策略端 `ema_cross_detector` 收敛为**日线单周期**，`scan-signals` 删掉两处 4H 分支
3. 接口端把 `ktype` 枚举收敛为 `1d|1w`，`/api/ema-cross-signals` 只保留日线分组，
   并在信号历史查询里**过滤**（不删除）历史遗留的 4H 记录
4. 前端删掉 4H 周期选项、4H 切换 tab 与相关判断分支，交易信号页默认周期改为日线

## Technical Context

**Language/Version**: Python 3.10+ / TypeScript(Vue 3 SFC)

**Primary Dependencies**: FastAPI、pandas、futu-api；Vue 3 + Vite + Ant Design Vue + lightweight-charts

**Storage**: SQLite `data/indicators.db`（**schema 不变、不迁移**；`ktype='4h'` 行冻结保留）

**Testing**: pytest（当前 97 项），前端人工走查 + 控制台检查

**Target Platform**: 本地开发（Windows）+ 线上 Linux（systemd + nginx）

**Project Type**: web-service + SPA（前端为独立仓库 `F:\TraderAnalysisFrontend`）

**Constraints**:
- 不得对 `kline_indicators` / `top_signal_log` / `bottom_signal_log` 执行 `DELETE` / `UPDATE`
- 日线 EMA 交叉信号的条数、强度、落库表必须与变更前一致
- 前后端是**两个仓库**，接口契约以后端为准，先改后端

**Scale/Scope**: 后端 8 个文件 + 3 条脚本 + 1 个测试文件；前端 3 个文件；文档 7 处

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 判定 | 结论 |
|---|---|---|
| **I. 两套信号体系不可合并** | 本次不触碰 `total_score` 与利弗莫尔；被删的是 EMA 交叉（既不是均分因子，也不是利弗莫尔关键点）。移除后**没有新增**任何写入 `livermore_signal_log` 的路径，两套体系边界不变。 | ✅ 通过 |
| **II. 口径是事实** | 不涉及市场温度口径、阈值与仓位映射；`market_scorer` 只读 1d/1w，改动不进入其读路径。 | ✅ 不适用（无相关改动） |
| **III. 术语精确，混称即缺陷** | 本次要删的「4H 关键位」属 **Swing Pivot 支撑压力位**（`/api/analysis`），与利弗莫尔关键点无关。删文案时必须保证剩余描述仍能指回唯一定义，不能把两者写成同一件事。 | ⚠️ 需在文档改动中逐句核对 |
| **IV. 单一真相源，派生物不入库** | 不改 schema、不新增派生文件；DB 仍不入库。文档是描述层，随代码同步而非另建副本。 | ✅ 通过 |
| **V. 文档与代码必须同时为真** | `api.md`（ktype 枚举、端点响应）、`storage.md`（增量规则、表说明）、`architecture.md`（模块职责）、`troubleshooting.md`（4H 收盘规则）、`watchlist.md`（数据可得性）必须同步。历史段落**不删改**，加勘误行。 | ⚠️ 重点执行 |
| **VI. 规范先行** | 本 spec / plan / tasks 先于实现提交；属「删端点字段 + 改枚举」的 API 契约变更，本就走 SDD。 | ✅ 通过 |

**Constitution 连带影响**：§三 质量门写着「当前 97 项」。删掉 4 个 4H 测试后数字变化，
按该段自身要求「数字变了要同步改这里」更新，并在 CHANGELOG 记录**理由**（测试随功能下线而减少，不是覆盖率回退）。

## 技术方案

### 1. 采集端（不再拉 4H）

| 文件 | 改动 |
|---|---|
| `futu_strategy/config.py` | 删 `FOUR_HOUR_INDICATOR_CONFIG`、`INIT_4H_KLINE_COUNT` 及其注释 |
| `futu_strategy/daily_update.py` | `_KTYPE_MAP` 删 `"4h": K_240M`；`_INCREMENTAL_COUNT` 删 `"4h": 60`；删 4H 日期格式化分支；删第三次 `_update_ktype(..., "4h", ...)` 调用；限频注释从「3 次请求」改为「2 次请求」 |
| `scripts/refetch_klines.py` | `KTYPE_SPECS` 删 4H 项；docstring 用法示例删 4H 根数说明 |
| `scripts/backfill_klines.py` | 新标的与存量标的各删一段 4H 拉取；docstring/步骤标题同步 |
| `scripts/verify_market_clock_live.py` | 周期清单删 4H 项 |

`init_history.run_init` 本来就不拉 4H，无需改动（FR-002 天然满足，作为回归保护验证）。

### 2. 策略端（不再算 4H 交叉）

`ema_cross_detector.detect_ema_cross()` 收敛为**单周期日线**：

- 删除 `timeframe` 参数与 `suffix` 推导，信号类型固定为 `EMA_CROSS_BULL_1D` / `EMA_CROSS_BEAR_1D`
- 强度公式、`detail` 字段、`date` / `close` / `ema5` / `ema30` / `spread_pct` **全部保持原样**
- 理由：留着 `timeframe` 参数等于留一条随时能被误用的 4H 通道，与「彻底移除」不符；
  调用点只有 3 处（`cli.py` × 2、`api_server.py` × 1），一次改完成本极低

`cli.py` 的 `scan-signals` 两条路径（`--backfill` 与增量）各删：
`four_h_all = query_recent(..., "4h", ...)`、`four_h_slice` 构造、`detect_ema_cross(..., "4h")` 循环。

### 3. 接口端

| 端点 | 改动 | 兼容性 |
|---|---|---|
| `/api/indicators` | `ktype` 正则 `^(1d|4h|1w)$` → `^(1d|1w)$`；删 4H 标签映射与 Unix 时间戳转换块 | 4H 请求从 200 变 422（FastAPI 参数校验），符合 spec US3-SC3 |
| `/api/indicators/latest` | 同上正则收敛 | 同上 |
| `/api/analysis` | 正则 `^(1d|1w|4h)$` → `^(1d|1w)$` | 同上 |
| `/api/ema-cross-signals` | 实时分支删 `four_h_df` 检测；读库分支 SQL 加 `AND signal_type NOT LIKE '%4H%'`；响应删 `bull_4h` / `bear_4h` 两个键 | 前端同步改，属已确认的契约变更 |

**存储层过滤（不删数据）**：`query_top_signals` / `query_top_signals_all` / `query_bottom_signals` /
`query_bottom_signals_all` 统一追加 `AND signal_type NOT LIKE '%4H%'`。
理由：库里 626 条历史 4H 信号按 FR-008 保留，但按 FR-006 不得再被接口返回。
目前唯一含 `4H` 字样的信号类型就是 `EMA_CROSS_*_4H`，过滤条件无副作用。

### 4. 收盘规则

`market_clock.is_bar_closed()` 白名单收敛为 `("1d", "1w")`，删除 4H 分支与仅 4H 使用的
`_to_local_datetime()`；模块 docstring 的规则表、已验证事实段删除 4H 条目（**不是**改写事实，
而是这批事实随功能下线不再适用），保留 1d/1w 的半日市与跨市场结论。

`technical_analysis._clean_series()` 的 docstring 从「周线与 4H」改为「周线」——兼容逻辑保留，
因为周线仍可能出现 object dtype 含 `None`。

### 5. 前端（独立仓库）

| 文件 | 改动 |
|---|---|
| `views/Chart.vue` | 删 `<a-select-option value="4h">`；删 4H 相关注释与分支（若有按 ktype 的判断，收敛为 1d/1w） |
| `views/MomentumLeaders.vue` | 删「空转多/多转空」两个 4H 切换按钮；`emaTab` 整体移除，模板直接消费 `bull_1d` / `bear_1d`；`bullCount` / `bearCount` 只统计日线 |
| `components/IndicatorChart.vue` | `tickMarkFormatter` 的数字分支保留（防御性，不删逻辑），但把「4H 数据」注释改为中性描述；`bars_ago` 注释去掉 4H 字样 |

`api/trader.js` 的 `getEmaCrossSignals` 无需改（路径不变，仅响应少两个键）。

### 6. 测试

- `tests/test_market_clock.py`：删 4 个 4H 测试函数；`test_same_instant_us_intraday_hk_closed`
  中的两条 4H 断言删除，保留 1d/1w 断言（该测试的核心是时区，不是 4H）
- 新增**回归测试**：`is_bar_closed("4h", ...)` 在移除后必须返回 `True`（走「其他类型一律放行」的默认分支），
  锁住「不再拦截 4H」这一行为，避免以后有人误加回来
- 前端无自动化测试，采用人工走查（见 tasks 验收项）

### 7. 文档

| 文件 | 改法 |
|---|---|
| `docs/reference/api.md` | ktype 枚举表、`/api/indicators`、`/api/analysis`、`/api/ema-cross-signals` 响应示例与字段表同步；文末变更记录**追加**新条目（旧条目保留） |
| `docs/reference/storage.md` | 表结构注释 `ktype '1d'/'1w'/'4h'` → 标注 4H 已冻结；增量更新规则删 4H 行 |
| `docs/overview/architecture.md` | `ema_cross_detector.py` 描述改为日线；若列了 4H 数据流则删 |
| `docs/guides/troubleshooting.md` | 4H 收盘规则段落加勘误行，说明已下线 |
| `docs/modules/watchlist.md` | 「能稳定拉取日线/周线/4H」→ 改为日线/周线 |
| `docs/modules/data-fetcher.md` | 若提到 4H 拉取则同步 |
| `docs/history/CHANGELOG.md` | 新增本次条目（含「为何保留库中 4H 数据」与「测试数变化理由」） |
| `README.md` | 若提到周期能力则同步 |
| `AGENTS.md` | 目录地图里「pytest 97 项」更新为新数字；§3 若有 4H 描述同步 |
| `.specify/memory/constitution.md` | §三「当前 97 项」更新为新数字（该段自带同步要求） |

## Project Structure

### Documentation (this feature)

```text
specs/002-remove-4h-cycle/
├── spec.md
├── plan.md      # 本文件
└── tasks.md
```

### Source Code (repository root)

```text
src/trader_analysis/
├── cli.py                                  # scan-signals 两处 4H 分支
└── futu_strategy/
    ├── config.py                           # 4H 指标配置与初始根数
    ├── daily_update.py                     # 4H 拉取与格式化
    ├── ema_cross_detector.py               # 收敛为日线单周期
    ├── market_clock.py                     # 4H 收盘判定
    ├── api_server.py                       # ktype 枚举 + EMA 端点 + 信号过滤
    ├── storage.py                          # 信号查询过滤
    └── technical_analysis.py               # 仅注释

scripts/
├── refetch_klines.py
├── backfill_klines.py
└── verify_market_clock_live.py

tests/test_market_clock.py

(F:\TraderAnalysisFrontend)
src/views/Chart.vue
src/views/MomentumLeaders.vue
src/components/IndicatorChart.vue
```

**Structure Decision**: 单后端项目 + 独立前端仓库。后端先改（接口契约以它为准），
前端随后跟进；两侧各自提交，不混在一个 commit 里。

## 风险与回滚

| 风险 | 影响 | 处置 |
|---|---|---|
| 漏删某处 4H 调用 | 日更仍打一次 4H 请求 | 用 `grep -rniE '4h\|240M\|FOUR_HOUR'` 做收尾扫描，命中数应为 0（文档冻结说明除外） |
| 前端默认 tab 未改 | 交易信号页打开即空 | `emaTab` 直接删除而非改默认值，从结构上消除空状态 |
| 过滤条件误伤日线信号 | 日线信号变少 | 过滤只匹配 `%4H%`；用变更前后同一天日线信号条数对比验证（SC-006） |
| 历史 4H 行被误删 | 不可逆 | 全程不执行任何写库 SQL；实现前先 `cp data/indicators.db data/_backup/…` 留快照 |
| 旧链接 4H 参数报 500 | 前端把它当故障 | FastAPI `pattern` 校验天然返回 422，不写自定义异常 |

**回滚**：纯代码变更，`git revert` 即可；数据未动，无需回滚数据。线上按流水线重新部署上一个 sha。

## Complexity Tracking

无违反项，本表不填。
