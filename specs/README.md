# specs/ —— 事前意图（Spec-Driven Development 产物）

> **这里放"我打算做什么"**。代码实际是什么样在 `docs/`，改过什么在 `docs/history/CHANGELOG.md`。
>
> 三者时态不同，不要互相替代：
>
> | 目录 | 时态 | 回答 |
> |---|---|---|
> | `.specify/memory/constitution.md` | 恒常 | 什么不能做 |
> | `specs/<feature>/`（本目录） | 未来 | 打算做什么、怎么验收 |
> | `docs/` | 现在 | 代码实际是什么样 |
> | `docs/history/CHANGELOG.md` | 过去 | 何时改的、为什么改 |

## 目录命名

```
specs/001-<ascii-slug>/
├── spec.md      做什么（需求 + 验收标准），不写技术方案
├── plan.md      怎么做（技术方案），含 Constitution Check 段
└── tasks.md     拆成可执行任务
```

- 编号 `NNN` 从 001 递增，**不复用、不回收**（删掉一个 feature 后编号也不补回去）。
- slug **必须 ASCII**。中文描述会让脚本生成中文目录名（实测：`001-给持仓页增加按行业分组`），
  Windows + git 下容易踩编码问题。写法：

  ```bash
  bash .specify/scripts/bash/create-new-feature.sh --short-name "position-industry-group" "给持仓页增加按行业分组"
  ```

  中文留在 `spec.md` 正文里，不进路径。

## 三件套的边界（最容易写错的地方）

**`spec.md` 只写"做什么"和"怎么算做完了"，不写技术选型。**
一旦在 spec 里写"用 Redis 缓存"，后面 `plan.md` 就失去意义了 —— 而且当真要换方案时，
你会不知道该改哪份文件。

- ✅ 写：用户场景、优先级、功能需求、验收标准（可度量）、明确的边界与不做的事
- ❌ 不写：库选型、表结构、接口签名、目录布局、性能实现手段

**`plan.md` 才写"怎么做"**，且必须包含 **Constitution Check** 段：
逐条对照 `.specify/memory/constitution.md` 的 6 条原则，勾选或写明不适用的理由。
**不适用的原则也要写一行**，不能整段省略 —— 省略等于没检查。

**`tasks.md`** 里每个任务要能独立验证。不要把"实现整个模块"写成一条任务。

## 硬约束

- **不得写入**真实账户标识、资产数值、持仓数量与成本、`.env` 内容、token、私钥。
- **不得写入仓位意图**（目标权重、标定区间、分批比例、加仓闸门）。
  这类内容只看 `data/target_allocation.json` 与 `GET /api/allocation`。
  spec 里最多写"由配置驱动，具体值不在文档内"。
- 示例数据必须虚构，并标注"示例数据为虚构值"。

详见 `.specify/memory/constitution.md` §二。

## 生命周期

1. 新建 → `spec.md` 状态 `Draft`
2. `clarify` 消歧后 → `Clarified`
3. `plan` + `tasks` 完成 → 可实施
4. 实现并 `converge` 到 Converged → `spec.md` 状态改 `Implemented`
5. **不删除**。功能下线时在 `spec.md` 顶部加一行 `> ⚠️ 已下线（日期）：原因`，保留目录。

历史目录不重写。发现当初写错了，加勘误行，不要改原文 —— 这条与 `docs/` 的规则一致。

## 什么时候可以不走这里

豁免清单（直接改代码，不需要 spec）：拼写与文案更正、单行 bug、版本号、纯文档措辞、注释。

小 bug 修复走 `bug` 扩展（`assess → fix → test`），不强制走完整 SDD。
装了扩展才有这三条命令：`specify extension add bug`。

判断标准与完整清单见 constitution §一.VI。
