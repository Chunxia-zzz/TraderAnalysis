# Feature Specification: 移除 4H 周期相关的全部功能与逻辑

**Feature Branch**: `002-remove-4h-cycle`

**Created**: 2026-11-08

**Status**: Implemented — 后端 95 项测试全绿、接口 4H 返回 422、4H 数据零变化、前端走查通过；
已推送上线（后端 `036a684` / 前端 `d052ba1`，CI 全绿，deploy 双双 success，线上冒烟验证通过）

**Input**: User description: "彻底移除项目中所有与4H周期相关的功能与逻辑：数据库中已存在的4H历史数据保持原样保留，无需删除或迁移；行情更新流程不再拉取4H K线；策略层不再计算4H的多转空和空转多信号；前端不再展示4H图表、4H关键位及任何其他4H相关展示。"

## 背景

4H 周期于 2026-07-21 随「4H EMA 交叉信号」一并引入（commit `4a539e3`），此后承担三项职能：
拉取入库、EMA5/EMA30 交叉信号、K 线图 4H 视图与 4H 关键位。

引入三个多月后，实测结论是**这套策略没有边际价值**：

- 全库 4H 复算（50,395 根 / 199 只 / 2,592 次交叉）：空转多信号在 10 根后跑输全样本基准
  （−0.29% vs +0.26%），多转空信号之后价格反而上涨（+0.85%），多空收益差在所有持有周期均为负，
  胜率 47–50% 接近抛硬币。对照日线同口径，20 根多空差 +1.78pp、胜率 53.5%，仍有残余信息。
- 信号采集本身还有结构性偏差：`scan-signals` 的 4H 逻辑只判定「每个交易日最后一根 4H」，
  而实测 61.5%（1,594/2,592）的交叉发生在当日 13:30 / 12:00 那根，永远采集不到。
  库里 626 条 4H 信号只是偏斜子集，不能当完整序列使用。
- 成本侧：日更每标的 1 次 `K_240M` 请求（199 次/天，占日更总请求 1/3）；
  库里 56,166 行、约占 `kline_indicators` 的 43.5%。

「4H K 线数据」与「4H EMA 交叉策略」是两层可分离的能力。本 feature **只下线 4H 相关的代码路径**，
**不动库里的历史数据**——数据保留原样，作为事后复盘的原样凭证；但不再新增、不再计算、不再展示。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 日更不再拉取 4H K 线 (Priority: P1)

执行日常行情更新时，系统只拉日线与周线，不再请求 4H 周期；4H 行数不再增长，日线与周线的更新结果与变更前完全一致。

**Why this priority**: 这是每天都会跑一遍的主链路，也是 4H 成本的唯一来源。若只删策略不删拉取，等于白付 1/3 的行情额度。

**Independent Test**: 记录 `SELECT COUNT(*) FROM kline_indicators WHERE ktype='4h'`，跑一次 `trader-analysis update`（可只指定 1~2 只标的），确认计数不变、日志中不出现 `4h` 新增记录、1d/1w 正常新增。

**Acceptance Scenarios**:

1. **Given** 本地库已有 4H 历史，**When** 执行行情更新，**Then** 4H 行数不变，且 1d/1w 正常写入
2. **Given** 一只全新标的没有任何 K 线，**When** 执行全量初始化（`init`）与增量更新，**Then** 只产生 1d/1w 数据，不产生 4H

---

### User Story 2 - 策略层不再产出 4H 信号 (Priority: P1)

信号扫描不再计算 4H 的 EMA 空转多/多转空；已有 4H 交叉信号不再通过任何 API 返回。日线 EMA 交叉信号保持现有行为不变。

**Why this priority**: 无边际价值的信号留在页面上，会持续消耗注意力并在回看时误导判断。

**Independent Test**: 跑一次 `trader-analysis scan-signals`，确认信号表不新增 `EMA_CROSS_*_4H`；请求 `/api/ema-cross-signals`，确认响应中不存在 4H 分组且日线分组内容与变更前一致。

**Acceptance Scenarios**:

1. **Given** 库里已有 626 条 4H 交叉信号，**When** 扫描信号，**Then** 不新增任何 `_4H` 记录，日线信号照常新增
2. **Given** 请求 `/api/ema-cross-signals`，**When** 不传日期（实时计算）或传日期（读库），**Then** 响应只含日线分组
3. **Given** 查询近期顶/底信号，**When** 读库返回，**Then** 不包含历史遗留的 4H 交叉记录

---

### User Story 3 - 前端不再展示任何 4H 内容 (Priority: P1)

个股 K 线页的周期选择只剩日线与周线；交易信号页的「空转多/多转空」只剩日线视图，页面默认落地在日线而不是 4H；不再有任何 4H 图表、4H 关键位或 4H 计数。

**Why this priority**: 后端删干净而前端仍留入口，用户点进去只会看到空图或空列表，体验比不做更差。

**Independent Test**: 打开个股 K 线页，周期下拉无「4H K线」；打开交易信号页，默认展示日线，切不到 4H；两页均无控制台报错。

**Acceptance Scenarios**:

1. **Given** 打开个股 K 线页，**When** 展开周期选择，**Then** 只有「日K」「周K」
2. **Given** 打开交易信号页，**When** 页面加载完成，**Then** 默认落在「空转多 + 日线」，且不存在 4H 切换按钮
3. **Given** 直接访问带 4H 参数的历史链接，**When** 后端收到请求，**Then** 返回参数校验失败（4xx），不是 500，也不返回 4H 数据

---

### User Story 4 - 历史 4H 数据原样保留 (Priority: P2)

库中已有的 56,166 行 4H K 线与 626 条 4H 信号保持原样，不删除、不迁移、不改写。文档明确说明这批数据已冻结、不再更新、不再被产品功能读取。

**Why this priority**: 删数据不可逆，且这批数据是「当初那套策略到底表现如何」的唯一原始凭证。

**Independent Test**: 变更前后各导出 `SELECT COUNT(*), MIN(date), MAX(date) FROM kline_indicators WHERE ktype='4h'`，三值完全一致。

**Acceptance Scenarios**:

1. **Given** 变更前后同一份数据库，**When** 对比 4H 行数与时间范围，**Then** 完全一致
2. **Given** 查阅文档，**When** 想知道 4H 数据现状，**Then** 能找到「已冻结、不再更新」的明确说明

---

### User Story 5 - 运维与补数脚本不再处理 4H (Priority: P2)

复权重拉、新标的回填、收盘规则验证这三条脚本只处理日线与周线。

**Why this priority**: 脚本是「出事后手工补救」的通道。若仍按 4H 规格拉取，会在无意义的数据上消耗额度，也会让人误以为 4H 仍在维护。

**Independent Test**: `python scripts/refetch_klines.py --dry-run <某标的>` 输出中不含 4H；`scripts/backfill_klines.py` 与 `scripts/verify_market_clock_live.py` 内不再出现 4H 周期。

**Acceptance Scenarios**:

1. **Given** 执行复权重拉，**When** 未显式指定周期，**Then** 只重拉 1d 与 1w
2. **Given** 执行收盘规则验证，**When** 跑完，**Then** 只验证 1d/1w，且结论与变更前一致

---

### Edge Cases

- **旧链接与书签**：`/api/indicators?ktype=4h`、`/api/analysis?ktype=4h` 从「返回数据」变成「参数非法」，必须返回 4xx 而不是 500，避免前端把它当成服务故障。
- **前端构建缓存**：Vite 旧 chunk 里仍带 4H 选项，需要强刷才能消失；验证时必须 Ctrl+Shift+R。
- **库里遗留的 4H 信号**：不删，但任何读接口都不再返回，否则「已下线」的说法与事实不符。
- **半日市**：4H 因标签本身是闭市时刻，原本准时入库；移除后不再有这条规则，日线的 16:00 判定不受影响。
- **线上进程**：部署后旧进程可能仍持有 4H 相关缓存数据；重启即恢复，不需要数据修复。
- **周线与 4H 的共用代码**：`_clean_series()` 同时服务周线与 4H 的 object dtype 列，去掉 4H 后仍必须保留对周线的兼容。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 行情更新 MUST 只拉取 `1d` 与 `1w`，不得再请求 `K_240M`
- **FR-002**: 全量初始化 MUST 不产生 4H 数据（当前行为保持不变，属于回归保护）
- **FR-003**: 信号扫描 MUST 不再产出 `EMA_CROSS_BULL_4H` / `EMA_CROSS_BEAR_4H`
- **FR-004**: 日线 EMA 交叉信号（`EMA_CROSS_*_1D`）的行为、强度、落库表 MUST 保持不变
- **FR-005**: `/api/ema-cross-signals` MUST 不再返回 4H 分组；日线分组结构与字段保持不变
- **FR-006**: 顶/底信号查询接口 MUST 不再返回历史遗留的 4H 交叉记录（只过滤，不删数据）
- **FR-007**: `/api/indicators`、`/api/indicators/latest`、`/api/analysis` 的 `ktype` MUST 只接受 `1d` / `1w`
- **FR-008**: 库中已有 4H K 线行与 4H 信号行 MUST 保持原样，不执行任何 `DELETE` / `UPDATE` / 迁移
- **FR-009**: 前端个股 K 线页 MUST 移除 4H 周期选项及其相关判断分支
- **FR-010**: 前端交易信号页 MUST 移除 4H 切换，且默认周期改为日线
- **FR-011**: 复权重拉 / 新标的回填 / 收盘验证三条脚本 MUST 不再包含 4H 周期
- **FR-012**: 文档 MUST 更新为「4H 已下线、历史数据冻结保留」，并说明为何无需删除数据
- **FR-013**: 评分、市场温度、利弗莫尔、每日优选、网格、持仓 / 止盈止损 MUST 不受影响

### Key Entities

- **4H 历史数据**：`kline_indicators` 中 `ktype='4h'` 的行，冻结保留，只读，不再增长。
- **4H 信号记录**：`top_signal_log` / `bottom_signal_log` 中 `signal_type` 含 `_4H` 的行，冻结保留，接口层过滤。
- **周期（ktype）**：产品层面允许的取值收敛为 `1d` / `1w` 两种。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 变更后执行一次完整日更，4H 行数增量 **= 0**，1d/1w 增量与变更前同量级
- **SC-002**: 变更后信号扫描产生的 `_4H` 记录 **= 0** 条
- **SC-003**: 库中 4H 行数维持 **56,166**（±0），最早 / 最晚日期不变
- **SC-004**: `pytest -q` 全绿，且失败数为 **0**
- **SC-005**: 前端 K 线页与交易信号页人工走查：无 4H 入口、无空状态、无控制台异常
- **SC-006**: 变更后日线 EMA 交叉信号在相同数据日的条数与内容与变更前一致（抽查 3 个交易日）

## Assumptions

- 用户确认不再使用 4H K 线图与 4H 关键位做人工看盘；这是本 feature 删除前端入口的前提。
- 4H 历史数据保留在同一个库、同一张表，不迁移到归档库；因此磁盘占用不会下降。
- 遗留的 4H 信号行不做物理删除，只在读取层过滤；若日后要清理，属于独立的数据维护动作。
- 日线与周线的数据链路、指标计算与信号逻辑不因本次变更发生任何改变。
- 线上部署沿用现有流水线（push main → check 绿 → deploy），本次不引入新的部署步骤。
