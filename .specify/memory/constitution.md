# TraderAnalysis Constitution

> 本文件是**原则层**：约束 AI 在这个仓库里做决策时的边界与优先级顺序。
>
> - **操作细节**（命令、路径、环境坑、Windows 前置 `export`）在 `AGENTS.md`，此处**不重复** —— 重复即产生第二份真相。
> - **现状描述**在 `docs/`（事后：代码实际是什么样）。
> - **本次变更的意图**在 `specs/<feature>/`（事前：我打算做什么）。
>
> 每条原则都带 **判定**：给出一个可执行的检查方式。做不到可判定的规则，不应写进本文件。

---

## Core Principles

### I. 两套信号体系不可合并 (NON-NEGOTIABLE)

`total_score` 是 6 因子**均值回归**（越跌分越高，等价于买超卖）；`livermore_signal_log` 是**关键点突破**（买突破）。**两者方向相反，这是刻意设计，不是历史包袱。**

约束：

- 利弗莫尔信号**不得**并入 `total_score`，**不得**参与 6 因子的加权或归一化。
- 利弗莫尔信号**不得**写入 `top_signal_log` / `bottom_signal_log`；它独立落库、独立 API、独立页面（`/livermore`）。
- 任何"把两套信号统一起来"的提案，必须先修改本条并说明为什么方向相反不再是问题 —— **不能以"简化"为理由直接实现**。

**判定**：在 `src/` 内，写入 `top_signal_log` / `bottom_signal_log` 的代码路径与利弗莫尔检测路径不相交；`total_score` 的计算函数签名不接收利弗莫尔产出。

### II. 口径是事实，不是可调参数 (NON-NEGOTIABLE)

**市场温度分数越高 = 越恐慌 = 越该加仓。** 该口径于 2026-10-19 做过反向，940 天历史数据已镜像迁移。

约束：

- **不得改回旧口径**，也不得新增与"高分=恐慌"方向相反的映射、阈值或文案。
- 跨 2026-10-19 的温度分数**不可直接比较大小**，涉及跨期对比时必须显式说明。
- 温度是**三维**（50/35/15），不是六维；已废弃的维度不得复活。

**判定**：仓位映射函数对输入温度分数单调递增；`docs/modules/market-temperature.md` §4.0 的口径快照与代码一致。

### III. 术语精确，混称即缺陷

**「支撑压力位」≠「利弗莫尔关键点」。** 前者是 Swing Pivot 聚类，后者是平台突破体系，两者可以同时画在同一张 K 线上，但不是同一套概念。

约束：

- 术语必须在**四处**保持一致：代码标识符、API 字段名、用户可见文案、文档。
- 不允许用"关键位""关键点""支撑位"这类模糊词跨指两套体系；一旦出现，视为缺陷而非措辞问题。

**判定**：任一用户可见文案或 API 字段名中的关键位类术语，都能指回唯一定义章节。

### IV. 单一真相源，派生物不入库

| 对象 | 唯一真相源 | 派生/生成物（禁止手改） |
|---|---|---|
| 标的池 | SQLite `watchlist` 表 | — |
| 技能 | `skills/` | `.claude/skills/`、`.agents/skills/`、`.workbuddy/skills/` |
| 数据库 | 可由 `trader-analysis init` 重建 | `data/*.db`、`data/_backup/` |

约束：

- 同一事实只允许一处维护；其他位置只能留指针，不能并存副本。
- 派生物一律不入库：`data/*.db`、`data/_backup/`、`logs/`、`.venv/`、`__pycache__/`。
- **第三方技能不入库**（无再分发授权或属工具生成）：`skills/futuapi/`、`skills/install-opend/`、`.claude/skills/speckit-*`，按需重建。
- 技能改完必须跑 `python scripts/agent/sync_skills.py`，并可用 `--check` 验证无漂移。

**判定**：`git ls-files` 不含上表"派生/生成物"列的任何路径；`sync_skills.py --check` 退出码为 0。

### V. 文档与代码必须同时为真

**不允许"文档先写着"。** 文档描述的必须是当前代码的真实行为；做不到就如实标注不一致，不能留一个好看但错误的版本。

约束：

- 每次开发结束统一更新 `docs/history/CHANGELOG.md`、`docs/reference/api.md`、`README.md`。
  若某项确实无需改动（例如没动 API），必须在 CHANGELOG 里**明确说明为何无需改**，不能默默跳过。
- 历史段落不删改：保留原文 + 加一行 `> ⚠️ 勘误（日期）：…`。
- 线上配置改完，`docs/guides/ops/` 里的副本同步改。

**判定**：`skills/doc-code-consistency-audit` 可复现通过；`docs/` 内相对链接断链为 0。

### VI. 规范先行（Before code）

**非平凡变更先有 `specs/<feature>/spec.md`，再写代码。** 这是本项目引入 Spec-Driven Development 的唯一目的：让"当初想做什么"可被事后核对。

必须先写规范的变更（任一项命中即是）：

- 新增用户可见功能或页面
- 改动数据模型（表结构、字段语义、索引、约束）
- 改动 API 契约（新增/删除端点、改返回结构、改枚举值）
- 跨模块重构，或改动评分/温度/信号的计算口径
- 引入新依赖或新外部服务

**豁免**（直接改，不需要 spec）：拼写与文案更正、单行 bug、版本号、纯文档措辞、注释。

**小 bug 修复**走 `bug` 扩展的 assess → fix → test，不强制走完整 SDD。

**判定**：`git log` 中该 feature 的 `spec.md` 提交时间早于其实现提交；`plan.md` 的 Constitution Check 段已逐条勾选。

---

## 二、安全与数据边界（不可协商）

**红线：以下内容一律不入库** —— 富途 `acc_id`、账户资产金额、持仓明细、`.env` 内容、私钥、任何 token。

**该约束同样覆盖 `specs/` 与 `plan.md`。** spec 写的是"要做什么"，不是账户快照：

- 不得在 spec / plan / tasks 中记录真实账户标识、资产数值、持仓数量与成本。
- **仓位意图**（目标权重、现货标定区间、分批比例、加仓闸门）属可丢弃的运行期状态，
  只看 `data/target_allocation.json` 与 `GET /api/allocation` —— **不写进 `specs/`、`docs/`、`README.md`**。
  必要时只描述"由配置驱动"，不写具体数字。
- 文档与 spec 中的示例数据必须虚构，并标注"示例数据为虚构值"。

投递前自查（必须执行）：

```bash
git diff --cached | grep -iE "acc_id|token|password|secret|BEGIN .*PRIVATE"
```

**提交纪律**：禁用 `git add -A`（工作区常年有未跟踪运行产物），逐个 `git add <path>`。

---

## 三、开发工作流与质量门

**三层的分工不要混**：

| 层 | 位置 | 回答的问题 | 时态 |
|---|---|---|---|
| 原则 | 本文件 | 什么不能做 | 恒常 |
| 事前 | `specs/<feature>/` | 我打算做什么、怎么验证 | 未来 |
| 事后 | `docs/` | 代码现在实际是什么样 | 现在 |
| 历史 | `docs/history/CHANGELOG.md` | 何时改的、为什么改 | 过去 |

**流程**：

1. `/speckit-specify` → `specs/NNN-<feature>/spec.md`（做什么、验收标准，**不写技术方案**）
2. `/speckit-clarify`（可选，需求有歧义时）→ 把歧义落盘，不要靠对话记忆
3. `/speckit-plan` → `plan.md`，其中 **Constitution Check** 段必须逐条对照本文件
4. `/speckit-tasks` → `tasks.md`
5. `/speckit-implement` → 写代码
6. `/speckit-converge` → 找出代码与规范的剩余差距；有新增任务则重复 5–6 直到 Converged

**质量门**（每次实现结束）：

- `pytest -q` 全绿（当前 **113 项**，数字变了要同步改这里）
- 本地批量验证通过后才推送，不要每改一处就部署
- 提交信息用 `feat:` / `fix:` / `docs:` / `chore:` / `refactor:` 前缀

**环境约定**：杀进程用 PowerShell（`Get-Process | Stop-Process`），起服务用 bash，Vite 改动后 Ctrl+Shift+R 强刷。理由与命令见 `AGENTS.md` §5、§8。

---

## Governance

**优先级（冲突时自上而下裁定）：**

1. 本文件（原则层）
2. `AGENTS.md`（操作层：具体命令、路径、环境坑）
3. `docs/`（描述层）
4. `specs/<feature>/`（本次变更的局部约定）
5. 单次对话中的指令

**冲突处理**：

- 局部 spec 与原则冲突 → **先改本文件并记录理由**，不允许"这次破例"。破例一旦不留痕，原则就失效了。
- 本文件与 `AGENTS.md` 冲突 → 以本文件为准，并**同步修正 `AGENTS.md`**，不让两份文件长期打架。
- 本文件不收录操作细节。想加"某命令怎么写"，那是 `AGENTS.md` 的事。

**修订规则**：

- 改本文件必须在 `docs/history/CHANGELOG.md` 记一行，说明**为什么**改（不是改了什么）。
- 版本号语义化：原则增删 → MAJOR；原则内容调整 → MINOR；措辞澄清 → PATCH。

**合规检查**：`plan.md` 的 Constitution Check 段落，每个原则一行，勾选或写明不适用的理由。完全不适用的原则也要写，不能整段省略。

**Version**: 1.0.0 | **Ratified**: 2026-11-01 | **Last Amended**: 2026-11-01
