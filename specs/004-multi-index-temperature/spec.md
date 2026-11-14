# Feature Specification: 美股指数温度扩展到 6 个（新增 DIA / IWM / SOXX / RSP）+ 三级导航

**Feature Branch**: `004-multi-index-temperature`

**Created**: 2026-11-14

**Status**: Draft

**Input**: User description: "美股、黄金、比特币三个大 tab，美股下面细分指数用小 tab；加 RSP、IWM、SOXX、DIA；阈值全部共用一套，SOXX 标注为高波动周期股，温度参考意义有限；历史从 2023-01 开始补。"

## 背景

2026-11-10 把合并温度拆成 SPY / QQQ 两套（`specs/003-split-market-temperature`）后，用户认为两个指数不足以刻画美股结构，需要补上：

- **罗素 2000（IWM）**：小盘 / 风险偏好，与大盘背离时最灵敏
- **费城半导体（SOXX）**：用户第一大重仓方向（AVGO/TSM/ASML/AMD/NVDA/INTC）
- **道指（DIA）**：30 只蓝筹、价格加权
- **标普等权（RSP）**：与 SPY 的背离反映市场宽度（少数权重股拉抬 vs 普涨）

同时页面已到 5 个平级 tab，再加会挤，需要改成**三级结构**。

### 已验证的约束

1. **富途不提供指数本身的行情**：实测 `US.DJI` / `US.RUT` / `US.SOX` 的 `last_price` 均为 **0.00**；
   `US.DIA`(523.15) / `US.IWM`(277.54) / `US.SMH`(486.75) / `US.RSP`(221.16) 正常。
   → **只能用 ETF 代理**，页面上的「点位」是 ETF 价格，不是指数点位。
2. **历史长度不足**：`US.SOXX` 仅 256 根日线（约 1 年），而 ATH 回撤子项取「全部已存 K 线的最高点」，
   样本过短会让 ATH 回撤偏小 → 温度偏低。DIA / IWM / RSP 当前 **0 根**，需先入池补数。
3. **VIXY 不可用于波动率**：它是滚动期货组合，存在 contango 损耗，净值长期下行，与 VIX 指数非 1:1。
   系统虽保留 `MARKET_TEMP_VOL_CODE` 定义，但**不再使用**，本次也不采用。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 六个指数各有独立温度 (Priority: P1)

打开温度页的「美股」分组，能看到 6 个指数的温度：SPY、QQQ、DIA、IWM、SOXX、RSP，各自显示综合分、状态、建议仓位、三维度拆解与关键指标。

**Why this priority**: 这是本次需求的主体。

**Independent Test**: 请求 `/api/market-temperature`，`indexes` 长度为 6，`key` 集合等于 `{SPY,QQQ,DIA,IWM,SOXX,RSP}`；页面 6 个小 tab 均能切换且数值与接口一致。

**Acceptance Scenarios**:

1. **Given** 六只标的的日线与周线均已入库，**When** 执行 `trader-analysis temperature`，**Then** 写入 6 行（每指数一行），同一数据日重跑不翻倍
2. **Given** 打开温度页，**When** 切换任一小 tab，**Then** 显示该指数自己的分数、状态、仓位与三维度，不串数据
3. **Given** 某指数缺数据，**When** 计算温度，**Then** 只有该指数降级为「数据不足」，其余 5 个照常输出

---

### User Story 2 - 阈值全部共用一套 (Priority: P1)

六个指数使用**完全相同**的阈值（ATH 回撤 15% 满分、MA200 偏离 ±15% 映射），不做按指数校准。因此六个分数可以互相比大小，温差也有意义。

**Why this priority**: 用户明确要求「全部共用一套」，并接受由此带来的偏差。

**Independent Test**: 读取 `_INDEX_CONFIGS`，六个条目的 `ath_drawdown_zero` 与 `ma200_range` 完全相同。

**Acceptance Scenarios**:

1. **Given** 六份配置，**When** 逐项比较阈值，**Then** 完全一致，且与 2026-11-10 的 SPY/QQQ 取值相同
2. **Given** 任一指数温度升高，**When** 重新计算，**Then** 该指数建议仓位单调不降（口径不反转）

---

### User Story 3 - SOXX 必须带「高波动周期股」提示 (Priority: P1)

SOXX 的温度展示位置必须明确标注：半导体属高波动周期行业，阈值与宽基共用，其温度的**绝对水平与宽基不可直接比较**，参考意义有限。

**Why this priority**: 共用阈值 + 高波动 = SOXX 会系统性偏高。不加提示，用户（或未来的自己）会把「SOXX 长期极度恐慌」误读成买点。

**Independent Test**: 接口返回的 SOXX 记录含非空 `note`；页面在 SOXX 视图可见该提示文案。

**Acceptance Scenarios**:

1. **Given** 请求 `/api/market-temperature`，**When** 找到 `key == "SOXX"`，**Then** `note` 非空且说明高波动/周期属性
2. **Given** 打开 SOXX 视图，**When** 页面渲染完成，**Then** 提示文案可见，且不与状态标签混淆

---

### User Story 4 - 三级导航：大 tab + 细分小 tab (Priority: P2)

温度页顶部为三个大 tab：**美股 / 黄金 / 比特币**；选中「美股」时，下方出现 6 个细分指数的小 tab（SPY / QQQ / DIA / IWM / SOXX / RSP）与「温差」视图。

**Why this priority**: 5 个平级 tab 已占满一行，6 个指数 + 温差共 7 个小 tab，必须分组。

**Independent Test**: 页面默认落在大 tab「美股」+ 小 tab「SPY」；切到黄金/比特币时小 tab 行消失；返回美股时保留上次选中的小 tab。

**Acceptance Scenarios**:

1. **Given** 打开页面，**When** 加载完成，**Then** 大 tab 选中「美股」，小 tab 选中「SPY」
2. **Given** 处于美股分组，**When** 点击「黄金」，**Then** 显示黄金温度，小 tab 行不显示
3. **Given** 从黄金切回美股，**When** 渲染完成，**Then** 小 tab 仍停在切换前选中的那个指数
4. **Given** 温差视图选中，**When** 切换大 tab 后再回来，**Then** 仍可看到温差视图

---

### User Story 5 - 历史从 2023-01 补齐 (Priority: P2)

四只新增标的的日线与周线补到 2023-01 起；温度历史仍从 2025-01-01 起算（与 SPY/QQQ 一致）。

**Why this priority**: 历史太短会让 ATH 回撤子项失真（SOXX 只有 1 年）。

**Independent Test**: 查 4 只新标的的 `MIN(date)`，不晚于 2023-01-31；`market_temp_split` 中各指数的首日均为 2025-01-02。

**Acceptance Scenarios**:

1. **Given** 补数完成，**When** 查询 4 只新标的日线，**Then** 行数均 ≥ 700 且最早日期 ≤ 2023-01-31
2. **Given** 温度回算完成，**When** 按 code 分组统计，**Then** 6 个指数行数一致，首日均为 2025-01-02

---

### User Story 6 - 文档与台账口径不变 (Priority: P3)

接口文档、温度模块文档、README、CHANGELOG 同步为 6 个指数；**台账仍只记 SPY / QQQ**，不因指数变多而加列。

**Why this priority**: 台账是「每日一行的大盘代表」，列数随指数增长会失控。

**Independent Test**: 文档中指数清单为 6 个；台账字段仍为 12 列。

**Acceptance Scenarios**:

1. **Given** 文档，**When** 检索指数清单，**Then** 与代码 `INDEX_KEYS` 完全一致
2. **Given** 台账，**When** 查看字段，**Then** 仍为 12 列，未新增指数列

---

### Edge Cases

- **ETF 与指数点位不同**：页面显示 DIA ≈ 523 而非「道指 47000」，必须在文案上说明是代理 ETF，不能让人误以为是点数。
- **RSP 的语义**：RSP 与 SPY 背离表示市场宽度变化，不是「第 7 个大盘温度」；页面上要与宽基同列展示，但解读时不可简单比大小。
- **SOXX 拆股**：2026-11 曾发生 3:1 拆股并修复过假断层；本次全量重拉必须用 QFQ，重拉后要核对 ATH 回撤不再异常。
- **补数与日更的边界**：`refetch_klines.py` 会 DELETE 再插入；执行前必须备份 DB，且**不能在日更 update 运行期间执行**。
- **短历史指数的 ATH**：若某指数入库起点晚于其历史 ATH，则 ATH 回撤会被低估。补到 2023-01 后需抽查每只的 ATH 日期是否落在样本区间内。
- **小 tab 过多**：6 个指数 + 温差 = 7 个，窄屏（<1280px）会换行，需允许换行而不是溢出隐藏。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 为 SPY / QQQ / DIA / IWM / SOXX / RSP 六个指数各计算一套三维温度（50/35/15）
- **FR-002**: 六个指数 MUST 共用同一套阈值（`ath_drawdown_zero = 0.15`、`ma200_range = 0.15`），不按指数校准
- **FR-003**: SOXX 记录 MUST 携带 `note` 字段，说明「半导体属高波动周期行业，与宽基共用阈值，温度的绝对水平不可与宽基直接比较」
- **FR-004**: 接口 `indexes[]` MUST 返回 6 条，顺序固定为 SPY / QQQ / DIA / IWM / SOXX / RSP
- **FR-005**: 温度计算与落库 MUST 幂等（同一数据日重跑不产生重复行）
- **FR-006**: 单指数数据不足 MUST 只降级该指数，不影响其余
- **FR-007**: 四只新增标的的日线 MUST 补齐到 2023-01 起，周线同步补齐
- **FR-008**: 温度历史 MUST 仍从 2025-01-01 起算，六个指数首日一致
- **FR-009**: 前端 MUST 采用三级导航：大 tab（美股 / 黄金 / 比特币）+ 美股下的小 tab（6 指数 + 温差）
- **FR-010**: 切换大 tab 时 MUST 保留美股分组上次选中的小 tab
- **FR-011**: 温差 MUST 维持「SPY − QQQ」的既有定义，不因新增指数而改变
- **FR-012**: 台账字段 MUST 保持 12 列不变，不新增指数列
- **FR-013**: 文档 MUST 同步为 6 个指数，并写明「ETF 代理、非指数点位」
- **FR-014**: 个股评分、利弗莫尔、信号扫描、目标仓位 MUST 不受影响；新增 4 只 ETF 进入标的池后被评分属预期副作用

### Key Entities

- **指数温度记录**：某数据日 + 某指数（6 选 1）的唯一温度结果，字段与 003 一致
- **指数代理标的**：`US.SPY` / `US.QQQ` / `US.DIA` / `US.IWM` / `US.SOXX` / `US.RSP`，均为美股 ETF
- **分组**：大 tab 三组（美股 / 黄金 / 比特币）；「黄金」「比特币」仍复用单资产温度，结构不变

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `/api/market-temperature` 的 `indexes` 长度为 **6**，`key` 顺序与 FR-004 一致
- **SC-002**: `market_temp_split` 中 **6 个指数 × 465 个交易日** 均有记录，各指数首日均为 2025-01-02
- **SC-003**: 四只新增标的日线行数 **≥ 700**，最早日期 **≤ 2023-01-31**
- **SC-004**: 同一数据日连续执行 3 次温度计算，总行数不变（幂等）
- **SC-005**: `pytest -q` 全绿，失败数 0
- **SC-006**: 页面人工/无头走查：3 个大 tab + 7 个小 tab 切换正常、无控制台错误、SOXX 提示可见
- **SC-007**: 新增 4 只 ETF 的 `total_score` 与信号不影响既有标的（抽查 5 只原有标的评分不变）
- **SC-008**: `docs/reference/api.md` 与实测响应逐字段一致

## Assumptions

- 用户已确认「全部共用一套阈值」，并接受 SOXX 系统性偏高、DIA 系统性偏低；不要求按指数校准。
- 用户已确认历史从 **2023-01** 起补（SPY/QQQ 现有数据从 2022-06 起，差异只影响 ATH 观察窗口）。
- 用户已确认新增 **RSP / IWM / SOXX / DIA** 四个，与现有 SPY / QQQ 合计 **6 个**小 tab（对话中提到的「5 个」按 6 个执行，删减只需改配置）。
- 不使用 VIXY 作为波动率输入：其净值受 contango 损耗，与 VIX 指数非 1:1。
- 页面「点位」显示 ETF 价格，不引入新的指数行情数据源。
- 台账继续只记 SPY / QQQ 作为大盘代表，不随指数数量扩张。
