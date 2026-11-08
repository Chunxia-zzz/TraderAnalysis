# Tasks: 移除 4H 周期相关的全部功能与逻辑

**Input**: `/specs/002-remove-4h-cycle/`（spec.md + plan.md）

**Prerequisites**: plan.md ✅、spec.md ✅

**Tests**: 后端 pytest（删 4 个 4H 用例 + 加 2 个）；前端无自动化测试，走查见 T039。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 归属用户故事（US1~US5）

---

## Phase 1: Setup

- [x] T001 备份数据库快照：`data/_backup/indicators.pre-remove4h.db`
- [x] T002 记录基线：`data/_backup/remove4h_baseline.json`（4H 56,166 行 / 2025-10-13~2026-11-06 / 信号 295+331）

---

## Phase 2: 采集端（US1）

**Goal**: 日更只拉 1d/1w，4H 行数不再增长。

- [x] T003 [US1] `config.py` — 删 `FOUR_HOUR_INDICATOR_CONFIG`、`INIT_4H_KLINE_COUNT`
- [x] T004 [US1] `daily_update.py` — `_KTYPE_MAP` / `_INCREMENTAL_COUNT` 删 4h、删 4H 日期格式化分支、删第三次 `_update_ktype`、限频注释 3→2
- [x] T005 [P] [US1] `scripts/refetch_klines.py` — `KTYPE_SPECS`、日期格式化、`--ktypes` 默认值、docstring
- [x] T006 [P] [US1] `scripts/backfill_klines.py` — 重写为「新标的 1d/1w 补数」，删存量 4H 重拉与 `--only-4h`
- [x] T007 [P] [US1] `scripts/verify_market_clock_live.py` — 重写为 1d/1w 验证，删 4H 断言

**Checkpoint**: ✅ `grep -rniE '4h|240M' src scripts tests` 仅剩「已下线」说明文字

---

## Phase 3: 策略端（US2）

**Goal**: 不再产生 `EMA_CROSS_*_4H`，日线信号行为不变。

- [x] T008 [US2] `ema_cross_detector.py` — 删 `timeframe` 参数与 `suffix`，信号固定 `_1D`；`detail.timeframe` 保留 `"1d"` 以维持落库同构
- [x] T009 [US2] `cli.py` — `--backfill` 分支删 `four_h_all` / `four_h_slice` / 4H 检测循环
- [x] T010 [US2] `cli.py` — 增量分支同上（含 `query_recent(code, "4h", limit=120)`）
- [x] T011 [US2] `api_server.py` — `/api/ema-cross-signals` 实时分支删 `four_h_df`、读库改精确类型、响应删 4H 键
- [x] T012 [US2] `storage.py` — 4 个信号查询函数加 `AND signal_type NOT LIKE '%4H%'`（只过滤，不删数据）

**Checkpoint**: ✅ 库副本上跑 `scan-signals`：新增 8 条 EMA 全为 `_1D`，4H 信号数 626 → 626

---

## Phase 4: 接口与收盘规则（US2 / US3）

- [x] T013 [US3] `api_server.py` — `/api/indicators` 正则 `^(1d|1w)$`、删 4H 标签映射与时间戳转换
- [x] T014 [P] [US3] `api_server.py` — `/api/indicators/latest` 正则收敛
- [x] T015 [P] [US3] `api_server.py` — `/api/analysis` 正则 `^(1d|1w)$`
- [x] T016 [US1] `market_clock.py` — 白名单 `("1d","1w")`、删 4H 分支与 `_to_local_datetime`、docstring 重写
- [x] T017 [P] `technical_analysis.py` — `_clean_series` docstring 去掉 4H（兼容逻辑保留）

**Checkpoint**: ✅ `4h` 请求返回 422（非 500）

---

## Phase 5: 前端（US3）— 独立仓库 `F:\TraderAnalysisFrontend`

- [x] T018 [P] [US3] `Chart.vue` — 删 4H 周期选项；两处「4H/1W 不请求」注释改为「周线」
- [x] T019 [US3] `MomentumLeaders.vue` — 删两个 4H 切换按钮与 `emaTab`；`bullFiltered`/`bearFiltered` 直读 `*_1d`；计数只算日线；清 `.ema-tabs`/`.ema-tab` 死样式
- [x] T020 [P] [US3] `IndicatorChart.vue` — 两处 4H 注释改为中性描述（时间戳分支保留作防御）

**Checkpoint**: ✅ `npm run build` 通过；`dist/assets` 不含 `bull_4h` / `bear_4h` / `4H K线`

---

## Phase 6: 测试（质量门）

- [x] T021 `tests/test_market_clock.py` — 删 4 个 4H 测试函数
- [x] T022 `tests/test_market_clock.py` — `test_same_instant_us_intraday_hk_closed` 删两条 4H 断言
- [x] T023 `tests/test_market_clock.py` — 新增 `test_4h_is_no_longer_policed`（4H 放行的防回归锁）
- [x] T023b `tests/test_market_clock.py` — 补回半日市 1d 断言 `test_daily_half_day_still_waits_until_1600`（原在 4H 用例里）
- [x] T024 `pytest -q` → **95 passed**

---

## Phase 7: 文档（US4 / FR-012）

- [x] T025 [P] `docs/reference/api.md` — ktype 枚举、EMA 端点响应与信号类型表；新增 3 条勘误行
- [x] T026 [P] `docs/reference/storage.md` — 表注释标注 4H 冻结；增量规则删 4H 行
- [x] T027 [P] `docs/overview/architecture.md` — `ema_cross_detector.py` 描述改日线
- [x] T028 [P] `docs/guides/troubleshooting.md` — 4H 收盘规则段加「已下线」勘误行
- [x] T029 [P] `docs/modules/watchlist.md` — 数据可得性去掉 4H
- [x] T030 [P] `docs/modules/data-fetcher.md` — 盘中半截 K 线段落删 4H
- [x] T031 `docs/history/CHANGELOG.md` — 新增 2026-11-08 条目
- [x] T032 `README.md` — `/api/indicators` 支持周期改 1d/1w
- [x] T033 `AGENTS.md` — pytest 用例数 97 → 95
- [x] T034 `.specify/memory/constitution.md` — §三 用例数 97 → 95

---

## Phase 8: 验证与收尾

- [x] T035 全仓扫描：代码/脚本仅剩「已下线」说明，无功能残留
- [x] T036 数据校验：4H 56,166 行、min/max 不变、信号 295+331 仍在；1d/1w 行数不变
- [x] T037 接口校验：`/api/indicators?ktype=4h` → 422、`/api/analysis?ktype=4h` → 422、
      `/api/ema-cross-signals` 键仅 `bull_1d`/`bear_1d`/`total`、`/api/top-signals?days=90` 含 4H = 0
- [x] T038 日更校验：`scan-signals` 在库副本上验证（4H 不增长、1D 正常写入）
- [ ] T039 前端浏览器走查：需用户强刷（Ctrl+Shift+R）后确认两页无 4H 入口、无空状态、无控制台异常
- [x] T040 `python scripts/agent/sync_skills.py --check` → 3 技能 × 3 目标全部一致
- [x] T041 spec.md 状态更新为 Implemented

---

## Dependencies

- Phase 2 / 3 / 4 依赖 T001 备份
- T008 先于 T009 / T010 / T011
- Phase 5 前端依赖 Phase 4 的后端契约
- Phase 6 依赖 Phase 3 / 4
- Phase 7 依赖 Phase 2~6 实际结果

## 遗留

- **T039**：浏览器逐页走查未自动化（本机无浏览器自动化通道），已用「构建通过 + 产物无 4H 字符串 + 源码无 4H 入口」替代。
  仍需用户在强刷后确认一次。
