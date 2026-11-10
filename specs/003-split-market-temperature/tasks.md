# Tasks: 市场温度按指数拆分（SPY / QQQ 独立计算与展示）

**Input**: `/specs/003-split-market-temperature/`（spec.md + plan.md）

**Prerequisites**: plan.md ✅、spec.md ✅

**Tests**: 后端 pytest 新增 7 类用例；前端无自动化测试，走查见 T023。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 归属用户故事（US1~US6）

---

## Phase 1: Setup

- [x] T001 备份数据库：`cp data/indicators.db data/_backup/indicators.pre-split-temp-$(date +%Y%m%d).db`
- [x] T002 记录基线：`market_score` 行数与首末日期（956 / 2022-09-30 / 2026-11-09）、11-09 合并值 74.9 与三维 76.2/87.3/41.3，写入 `logs/split-temp-baseline.md`
- [x] T003 记录 `total_score` 基线：11-09 全池 195 条评分快照（供 T021 比对恐慌加成是否失血）

---

## Phase 2: 计算端（US1 / US2）

**Goal**: 能算出两个指数的独立温度，且平均值等于旧合并值。

- [x] T004 [US1] `market_scorer.py` — 新增 `_INDEX_CONFIGS`（SPY / QQQ，阈值同为 0.15 / 0.15）
- [x] T005 [US1] `market_scorer.py` — 新增 `compute_index_temperature(key)`，复用 `_score_asset_*`，权重 50/35/15
- [x] T006 [US2] `market_scorer.py` — 新增 `compute_temperature_spread(spy, qqq)` 与 `spread_label()`
- [x] T007 [US1] `market_scorer.py` — 新增 `compute_index_temperature_history(key, start_date)`
- [x] T008 [US1] `market_scorer.py` — 删除合并路径：`_score_daily_tech` / `_score_weekly_tech` / `_score_price_position` / `_compute_score` / `calculate_market_temperature` / `backfill_market_temperature`（先 `grep -rn` 确认无残留调用）

**Checkpoint**: 库副本上 `compute_index_temperature` 得 SPY 70.3 / QQQ 79.4，平均 74.85 与基线 74.9 差 ≤0.5

---

## Phase 3: 存储端（US4 / US5）

- [x] T009 [US4] `storage.py` — `init_db` 增加 `market_temp_split` 建表（复合主键 `date+code`）+ 索引
- [x] T010 [US4] `storage.py` — 新增 `upsert_market_temp_split(date, code, result)`（`INSERT OR REPLACE`）
- [x] T011 [US1] `storage.py` — 新增 `query_latest_market_temp_split()` / `query_market_temp_split_history(start_date, code=None)`
- [x] T012 [US4] `storage.py` — 新增 `query_panic_composite()`：split 均值优先，回落 `market_score`
- [x] T013 [US5] `storage.py` — 删 `upsert_market_score`；`query_latest_market_score` / `query_market_score_history` 若无调用点一并删（冻结语义：只留数据，不留写路径）

**Checkpoint**: 同一日 upsert 两次，`SELECT COUNT(*) FROM market_temp_split WHERE date=?` 恒为 2

---

## Phase 4: 命令行与加成（US4 / FR-016）

- [x] T014 [US4] `cli.py` — `temperature` 改为写两指数；新增 `--since`（与 `--backfill` 互斥）；输出两行 + 温差
- [x] T015 [US4] `cli.py` — 恐慌加成取数改走 `storage.query_panic_composite()`
- [x] T016 [P] [US4] `runner.py` — 最新温度取数同上
- [x] T017 [US4] 跑一次性回算：`trader-analysis temperature --since 2025-01-01`，产出约 465×2 行

**Checkpoint**: `SELECT code, COUNT(*) FROM market_temp_split GROUP BY code` 两行均为 465 左右；最早日期 ≥ 2025-01-01

---

## Phase 5: 接口端（US1 / US2 / US3）

- [x] T018 [US1] `api_server.py` — `/api/market-temperature` 改为 `{date, indexes[], spread, gld_temp, btc_temp}`
- [x] T019 [US3] `api_server.py` — `/api/market-temperature/history` 改为 `{series[], spread[]}`，`start` 默认 2025-01-01 且更早一律截断
- [x] T020 [US1] `api_server.py` — 单指数数据不足时只降级该指数（FR-013），不让整响应 500

**Checkpoint**: 响应顶层无 `composite_score`；`spread.label` 与符号一致

---

## Phase 6: 测试（全故事）

- [x] T021 `tests/test_split_market_temperature.py` — 7 类用例：三维加权 / 旧口径等价 / 幂等 / 温差符号 / 数据不足降级 / 历史起点 / 恐慌加成连续
- [x] T022 全量回归：`pytest -q` 全绿；并把 11-09 全池评分重算与 T003 基线比对（均值偏差 >0.5 即中止）

**Checkpoint**: 失败数 0；评分未失血

---

## Phase 7: 前端（US1 / US2 / US3）

- [x] T023 [US1] `MarketTemperature.vue` — 视图切换改 `spy / qqq / spread / gold / btc`；SPY/QQQ 两张卡消费 `data.indexes[]`
- [x] T024 [US3] `MarketTemperature.vue` — 温差卡片 + 温差折线（正负分色），文案用后端 `spread.label`
- [x] T025 [US1] `api/trader.js` — 新增 `getMarketTemperatureHistory({days, start})`；删除对顶层 `composite_score` 的引用

**Checkpoint**: 温度页两张卡 + 温差图正常，无 `undefined`，控制台无报错，Ctrl+Shift+R 后一致

---

## Phase 8: 文档（US6）

- [x] T026 [P] [US6] `docs/reference/api.md` — 两端点新结构 + 字段表 + 虚构示例；旧结构加勘误行
- [x] T027 [P] [US6] `docs/modules/market-temperature.md` — §4.0 口径快照重写、温差定义、合并值冻结说明
- [x] T028 [P] [US6] `docs/reference/storage.md` — 新表说明、`market_score` 标注冻结
- [x] T029 [P] [US6] `docs/history/CHANGELOG.md` — 为什么拆 / 为什么冻结 / 为什么加成用平均 / 测试数校正理由
- [x] T030 [P] [US6] `README.md` — 温度能力描述同步
- [x] T031 [P] [US6] `AGENTS.md` + `.specify/memory/constitution.md` — 测试数统一为实测值（两份当前不一致：95 vs 97）

---

## Phase 9: 验证与收尾

- [x] T032 本地联调：后端 8000 + 前端 5173，温度页走查全绿
- [x] T033 线上同步：按流水线上线（push main → check 绿 → deploy），公网回读 `/api/market-temperature` 顶层无 `composite_score`
- [x] T034 `converge` 复核：spec 的 FR-001~FR-016 / SC-001~SC-008 逐条对照，未达成项补任务

---

## Dependencies

- Phase 2 完成后才能做 Phase 3（存储要写 scorer 的产出结构）
- T013 与 T015/T016 必须一起改，否则恐慌加成会读空
- Phase 4 的回算（T017）必须在 Phase 5 接口联调之前，否则接口无数据可读
- Phase 7 前端依赖 Phase 5 的契约定型
- Phase 8 文档必须在实现完成后一次性对齐（宪法 V）

## 风险提示（实现时逐条盯）

- **T013 删 `upsert_market_score` 前**必须确认 `cli.py` / `runner.py` 已改完，否则报 `AttributeError`
- **T017 回算耗时**：465 日 × 2 指数，每个切片要读 300 根日线，预计 3~6 分钟，必须后台跑
- **不要动 `score_results`**：T022 的重算比对只在副本上做，避免污染当日结果


---

## 收敛记录（2026-11-10）

| 项 | 结论 |
|---|---|
| FR-001 ~ FR-016 | 全部满足；逐条核对见下方「验证证据」 |
| SC-001 | (70.3 + 79.4)/2 = 74.85 vs 拆分前 74.9，差 0.05 ✅ |
| SC-002 | 温差 465 点，首点 2025-01-02（≥2025-01-01），无更早数据 ✅ |
| SC-003 | `market_score` 956 行、2022-09-30~2026-11-09 不变 ✅ |
| SC-004 | 同数据日重跑 3 次，行数恒为 2 ✅ |
| SC-005 | `pytest -q` = 110 passed ✅ |
| SC-006 | 无头浏览器走查 5 个视图，无控制台错误，截图 `logs/verify-spy-temp.png` / `logs/verify-spread.png` ✅ |
| SC-007 | `api.md` 两端点结构、字段表、示例已同步 ✅ |
| SC-008 | 192 只按 11-09 切片重算，0 处与基线不一致 ✅ |

**上线记录（2026-11-11）**

| 项 | 值 |
|---|---|
| 部署顺序 | **前端先、后端后**（先上后端会让旧页面读 `composite_score` 直接崩；先上前端只短暂显示空态） |
| 前端 | `c42a996`，run #8 success，线上资源 `MarketTemperature-UrPj4xEZ.js` |
| 后端 | `f20fe4b`，deploy job success，`/api/market-temperature` 回读 `indexes` + `spread` |
| 数据 | 部署后补 `scp data/indicators.db`（bytes 87,654,400 双向一致）—— **新表不会随代码部署**，这一步漏了就会报「暂无指数温度数据」 |
| 线上走查 | 5 个视图渲染正常、`undefined`/`NaN` 出现次数 0、控制台错误 0 |

**首次上线踩到的两件事**

1. 前端 CI 红在 `tests/unit/api.spec.js`：改默认参数时**没先跑 `npm run test:unit`**，只跑了 `npm run build`。
   教训：前端改动 push 前跑 `npm run lint && npm run test:unit && npm run build`（等同 `bash scripts/check.sh`）。
2. 后端 ruff 报 5 处（未用 import ×2、行过长 ×2、import 排序 ×1）——删掉合并路径后留下的死 import。
   `bash scripts/check.sh` 本地跑一次就能全抓到。
