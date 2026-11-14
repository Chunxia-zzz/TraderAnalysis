# Tasks: 美股指数温度扩展到 6 个 + 三级导航

**Input**: `/specs/004-multi-index-temperature/`（spec.md + plan.md）

**Prerequisites**: plan.md ✅、spec.md ✅

**Tests**: 后端 pytest 3 个文件改动；前端无新增单测，走查见 T016。

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

- [ ] T001 备份数据库：`cp data/indicators.db data/_backup/indicators.pre-004-20261114.db`
- [ ] T002 记录基线：6 只标的当前 K 线根数、`market_temp_split` 930 行、现有 5 只标的的 `total_score`（供 SC-007 比对）

---

## Phase 2: 数据补全（US5）

- [ ] T003 [US5] 入池 3 只新标的（DIA / IWM / RSP），`category='指数ETF'`；SOXX 已在池
- [ ] T004 [US5] `refetch_klines.py --dry-run` 看范围（4 只：DIA/IWM/RSP/SOXX）
- [ ] T005 [US5] 正式重拉：`python scripts/refetch_klines.py US.DIA US.IWM US.RSP US.SOXX`（避开日更）
- [ ] T006 [US5] 校验：日线 ≥700 根、最早 ≤2023-01-31、SOXX 最新收盘与 `get_market_snapshot` 一致、ATH 日期在样本内

**Checkpoint**: 4 只补数完成且 SOXX 无假断层

---

## Phase 3: 计算端（US1 / US2 / US3）

- [ ] T007 [US1] `market_scorer._INDEX_CONFIGS` 扩为 6 条，阈值全部 `0.15 / 0.15`
- [ ] T008 [US3] SOXX 配置加 `note`（高波动周期行业、绝对水平不可与宽基比）
- [ ] T009 [US1] `INDEX_KEYS` 改为 6 元组，顺序 SPY/QQQ/DIA/IWM/SOXX/RSP
- [ ] T010 [US3] `_build_index_result` / `_index_insufficient` 透传 `note`
- [ ] T011 [US1] 回算：`temperature --since 2025-01-01`（6 指数 × 465 天 ≈ 2790 行）

**Checkpoint**: 库中 6 个 code 各 465 行；重跑一次行数不变

---

## Phase 4: 接口端（US1 / US4）

- [ ] T012 [US1] `/api/market-temperature` 输出 6 条 index，每条补 `note` / `is_etf_proxy` / `group`
- [ ] T013 [US4] 顶层补 `groups` 描述（美股/黄金/比特币），供前端分组
- [ ] T014 [US1] `/api/market-temperature/history` 序列扩为 6 条（温差仍只用 SPY/QQQ）

**Checkpoint**: `indexes` 长度 6、顺序正确、SOXX 的 note 非空

---

## Phase 5: 测试（全故事）

- [ ] T015 更新 3 个测试文件：数量/顺序/note 断言；新增「6 份阈值完全一致」用例
- [ ] T016 全量回归：`pytest -q` 全绿；抽查 5 只原有标的 `total_score` 与 T002 基线一致

---

## Phase 6: 前端（US4）

- [ ] T017 `MarketTemperature.vue` — 大 tab（美股/黄金/比特币）+ 美股下小 tab（6 指数 + 温差），切换保留 `subView`
- [ ] T018 小 tab 行 `flex-wrap`；窄屏不溢出
- [ ] T019 SOXX 视图渲染 `note` 提示条（样式与状态标签区分）
- [ ] T020 点位文案标注「ETF 代理」，不写成指数点位

**Checkpoint**: 3 大 tab × 7 小 tab 切换正常、无控制台错误

---

## Phase 7: 文档（US6）

- [ ] T021 [P] `docs/reference/api.md` — indexes 6 条示例 + note/group/is_etf_proxy 字段表 + ETF 代理说明
- [ ] T022 [P] `docs/modules/market-temperature.md` — 6 指数清单、共用阈值、SOXX 例外、ETF 代理
- [ ] T023 [P] `docs/reference/storage.md` — `market_temp_split` 行数更新
- [ ] T024 [P] `docs/history/CHANGELOG.md` — 为什么加 / 为什么全共用 / 为什么 SOXX 提示 / 为什么不用 VIXY
- [ ] T025 [P] `README.md` + `AGENTS.md` + `constitution.md` — 指数清单与测试数同步

---

## Phase 8: 验证与上线（US1~US6）

- [ ] T026 本地：`bash scripts/check.sh` + `npm run lint && npm run test:unit && npm run build`
- [ ] T027 本地走查：6 指数 + 温差 + 黄金/BTC，无控制台错误
- [ ] T028 上线：前端先（新 UI 兼容旧接口会空态）→ 后端后 → **补 scp DB**（含 6 指数与新增 K 线）
- [ ] T029 线上验证：`indexes` 6 条、页面 7 小 tab、SOXX 提示可见
- [ ] T030 converge：逐条核对 FR-001~FR-014 / SC-001~SC-008

---

## Dependencies

- Phase 3 依赖 Phase 2（没有 K 线算不出温度）
- Phase 4 依赖 Phase 3（接口读库）
- Phase 6 依赖 Phase 4（契约先定）
- T028 的 scp 必须在前后端都部署完之后（新表数据不会随代码走）

## 风险提示

- **T005 与日更互斥**：`refetch_klines` 会 DELETE，绝不能和 `update` 同时跑
- **T011 耗时**：6 指数 × 465 天，按 003 实测算 2~7 分钟，必须后台跑
- **T015 会改既有断言**：003 的测试写死了 2 条，改动时要保留「温差只取 SPY/QQQ」的断言
