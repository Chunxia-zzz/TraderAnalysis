# Implementation Plan: 美股指数温度扩展到 6 个 + 三级导航

**Branch**: `004-multi-index-temperature` | **Date**: 2026-11-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-multi-index-temperature/spec.md`

## Summary

把指数温度从 2 个扩到 6 个（新增 DIA / IWM / SOXX / RSP），阈值保持全共用；前端从「5 个平级 tab」改为「3 个大 tab × 美股下 7 个小 tab」。

四处改动：

1. **数据**：4 只 ETF 入池 → `refetch_klines.py` 全量重拉（1000 日线 + 300 周线，覆盖 2023-01）
2. **计算**：`_INDEX_CONFIGS` 扩到 6 条，全部 `0.15 / 0.15`；新增 `note` 字段承载 SOXX 的高波动提示
3. **接口**：`indexes[]` 由 2 条变 6 条；新增 `note` / `group` 字段，前端据此分组
4. **前端**：三级导航；小 tab 允许换行；SOXX 视图显示提示条

## Technical Context

**Language/Version**: Python 3.10+ / Vue 3 SFC

**Primary Dependencies**: FastAPI、pandas、futu-api；Vue 3 + Vite + ECharts

**Storage**: SQLite；**不新增表、不改表结构**，只增加行（`market_temp_split` 从 930 → 2790 行）+ 新增 4 只标的的 K 线

**Testing**: pytest；前端 vitest + 无头浏览器走查

**Target Platform**: 本地 Windows + 线上 Linux（systemd + nginx）

**Project Type**: web-service + SPA（前端独立仓库）

**Constraints**:
- 六个指数阈值必须字面一致（spec FR-002），改动要在 review 中一眼可见
- `refetch_klines.py` 会 DELETE 再插入 → 执行前备份 DB，且避开日更 update
- 台账（资料库 `每日信号台账`）保持 12 列，不加指数列
- 前后端两个仓库，接口契约以后端为准

**Scale/Scope**: 后端 2 个文件（`market_scorer` / `api_server`）+ 测试 3 处；前端 1 个文件；文档 5 处；数据 4 只标的补数

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 判定 | 结论 |
|---|---|---|
| **I. 两套信号体系不可合并** | 只扩市场温度指数清单，不触碰 `total_score` 六因子与利弗莫尔。新增 4 只 ETF 会被 6 因子评分、参与信号扫描，但那是既有数据链路，不改变两套体系的边界。 | ✅ 通过 |
| **II. 口径是事实，不是可调参数** | 方向不变（高分=恐慌=加仓）；仍三维 50/35/15；**阈值一个字都没改**，只是多了 4 个使用同一阈值的指数。跨口径红线：SOXX 与宽基**共用阈值但不可比绝对水平**，必须靠 `note` 明示，否则等于制造一个「看似可比实则不可比」的陷阱。 | ⚠️ `note` 为必做项 |
| **III. 术语精确，混称即缺陷** | 新增「ETF 代理」概念：页面上的「点位」是 ETF 价格，不能写成「道指点位」。六个指数必须始终用「指数名 + 代理代码」表述（如「费城半导体（SOXX）」），不能混称。 | ⚠️ 文案逐处核对 |
| **IV. 单一真相源，派生物不入库** | 指数清单唯一源是 `_INDEX_CONFIGS`（后端），前端不复制阈值、不复制清单；分组的唯一源也由后端 `group` 字段给出。 | ✅ 通过 |
| **V. 文档与代码必须同时为真** | `api.md`（indexes 结构、note/group）、`market-temperature.md`（6 指数清单、共用阈值、SOXX 提示）、`storage.md`（行数变化）、`CHANGELOG`、`README` 同步。 | ⚠️ 重点执行 |
| **VI. 规范先行** | 本 spec/plan/tasks 先于实现；属「新增能力 + 改 API 契约」，必须走 SDD。 | ✅ 通过 |

**Constitution 连带影响**：无（测试数会变，按 §三 要求同步 `AGENTS.md` 与 `constitution.md`）。

## 技术方案

### 1. 数据补全

```bash
cp data/indicators.db data/_backup/indicators.pre-004-$(date +%Y%m%d).db   # 必须先备份
# 4 只入池（SOXX 已在池，跳过）
# 全量重拉：1000 根日线 / 300 根周线，覆盖 2023-01
python scripts/refetch_klines.py US.DIA US.IWM US.RSP US.SOXX
```

- `refetch_klines.py` 内部用 QFQ + `filter_closed_bars`，SOXX 的 3:1 拆股历史会被一并重算（消除假断层）
- 入池走 `watchlist_storage.add_stock`，`category` 标 `指数ETF`，便于在标的池页面识别
- 重拉后核对：日线 ≥ 700 根、最早日期 ≤ 2023-01-31、四只的 ATH 日期落在样本区间内

### 2. 计算端（`market_scorer.py`）

`_INDEX_CONFIGS` 扩为 6 条，阈值全部 `0.15 / 0.15`，新增两个字段：

```python
"SOXX": {
    "label": "费城半导体",
    "code_daily": "US.SOXX", "code_weekly": "US.SOXX",
    "ath_drawdown_zero": 0.15, "ma200_range": 0.15,
    "note": "半导体属高波动周期行业，与宽基共用阈值；温度的绝对水平不可与宽基直接比较，参考意义有限",
},
```

- `INDEX_KEYS = ("SPY", "QQQ", "DIA", "IWM", "SOXX", "RSP")` —— 顺序即接口顺序
- `_build_index_result` 透传 `note`；`_index_insufficient` 也带 `note`（降级时提示不消失）
- 温差定义不变：`SPY − QQQ`，只取这两个 key

### 3. 接口端（`api_server.py`）

`indexes[]` 每条新增：

| 字段 | 值 | 用途 |
|---|---|---|
| `group` | `"us_index"` | 前端分组依据；黄金/BTC 仍走顶层 `gld_temp` / `btc_temp` |
| `note` | 该指数的提示文案或 `null` | SOXX 必填，其余为 `null` |
| `is_etf_proxy` | `true` | 明确「点位是 ETF 价格」 |

响应顶层新增 `groups` 描述（可选，前端也可硬编码三大组）：

```json
"groups": [
  {"key": "us_index", "label": "美股", "index_keys": ["SPY","QQQ","DIA","IWM","SOXX","RSP"]},
  {"key": "gold", "label": "黄金", "index_keys": []},
  {"key": "btc", "label": "比特币", "index_keys": []}
]
```

### 4. 前端（`MarketTemperature.vue`）

- **大 tab**：`美股 / 黄金 / 比特币`（3 个），状态 `topView`
- **小 tab**：仅当 `topView === 'us_index'` 显示，7 个（6 指数 + 温差），状态 `subView`
- **记忆**：切走再回来保留 `subView`（用 `ref` 保持，不重置）
- **SOXX 提示**：`activeIndex.note` 非空时在 hero 下方渲染一条 `.note-bar`（浅黄底、不抢状态标签）
- **窄屏**：小 tab 行 `flex-wrap: wrap`，允许换行
- 温差视图保留原有「两点对比 + 折线」结构

### 5. 测试

| 文件 | 改动 |
|---|---|
| `tests/test_market_scorer.py` | `len(indexes) == 2` → `6`；key 集合断言更新；新增「6 份阈值完全一致」用例 |
| `tests/test_market_api.py` | `indexes` 顺序断言 6 条；新增 `note` / `is_etf_proxy` 断言（SOXX 有 note，SPY 无） |
| `tests/test_split_market_temperature.py` | `INDEX_KEYS` 长度断言；`test_two_rows_per_date` 改为按 6 个 key 写入后校验 6 行 |
| 前端 `tests/unit/api.spec.js` | 无接口参数变化，预计不动 |

### 6. 文档

| 文件 | 改法 |
|---|---|
| `docs/reference/api.md` | `indexes[]` 6 条示例、`note` / `group` / `is_etf_proxy` 字段表；补「ETF 代理非指数点位」说明 |
| `docs/modules/market-temperature.md` | §4.0.1 扩为 6 指数；新增「共用阈值 ⇒ 可跨指数比大小」与「SOXX 例外说明」；写明 ETF 代理 |
| `docs/reference/storage.md` | `market_temp_split` 行数 930 → 2790 |
| `docs/history/CHANGELOG.md` | 为什么加、为什么全共用阈值、为什么 SOXX 要提示、为什么不用 VIXY |
| `README.md` | 指数清单同步 |
| `AGENTS.md` / `constitution.md` | 测试数同步为实测值 |

## Project Structure

```text
specs/004-multi-index-temperature/
├── spec.md
├── plan.md      # 本文件
└── tasks.md

src/trader_analysis/futu_strategy/
├── market_scorer.py      # _INDEX_CONFIGS 6 条 + note 透传
└── api_server.py         # indexes 6 条 + note/group/is_etf_proxy

tests/test_market_scorer.py / test_market_api.py / test_split_market_temperature.py

(F:\TraderAnalysisFrontend)
src/views/MarketTemperature.vue
```

## 风险与回滚

| 风险 | 影响 | 处置 |
|---|---|---|
| refetch 误删 SOXX 历史 | 数据不可逆 | 执行前 `cp` 备份；`--dry-run` 先看范围 |
| SOXX 拆股断层未修好 | ATH 回撤失真 → 温度永久偏高 | 重拉后比对 `get_market_snapshot` 的 `last_price` 与库内最新收盘 |
| 补数期间并发日更 | `database is locked`，批量失败 | 补数与 `update` 不同时跑 |
| 6 个指数让 API 变慢 | 首屏等待 | 温度接口只读库（不重算），实测应 < 300ms；历史接口 `days` 上限不变 |
| 前端小 tab 溢出 | 窄屏错位 | `flex-wrap`；1280 宽下人工确认 |
| 台账误加列 | 列数膨胀 | spec FR-012 明确不加；改台账前先看 spec |

**回滚**：代码 `git revert`；数据侧 `market_temp_split` 删掉 4 个新 code 的行即可回到 2 指数状态（K 线保留无害）。

## Complexity Tracking

无违反项，本表不填。
