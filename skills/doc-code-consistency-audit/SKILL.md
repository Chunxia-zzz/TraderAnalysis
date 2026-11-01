---
name: doc-code-consistency-audit
description: 审计项目文档（README + docs/）与当前代码是否一致，找出并修正「文档写了但代码没有 / 代码有但文档没写」的每一处。当用户说「检查文档有没有要更新的」「文档和代码对不上了」「XX 文档还准吗」，或在功能开发/修 bug 收尾后需要同步文档时使用。含一套按「真实路由 → 数据模型 → 枚举常量 → 交叉引用编号」逐个比对的确定性流程、7 类高频失效模式清单、以及链接校验与提交口径。
---

# 文档与代码一致性审计

## 适用场景

- 用户问「还有哪些文档需要更新？」「文档跟代码对得上吗？」
- 一轮功能开发 / bug 修复收尾，需要把 README 与 docs/ 同步到「与当前功能完全一致」

> 用户的硬性约定：**文档必须与当前功能完全一致；未实现的功能要显式标注「裁剪未做」，
> 不能写成已交付。** 审计的产出不是「一份报告」，而是**改完的文档**。

## 核心原则

**不要靠读文档判断文档准不准 —— 要去读代码。** 文档里最危险的错误是"看起来很合理"的那种。
判定依据只有三个来源：`router` 的路由注册、`model` 的结构体、常量的定义处。

## 审计流程（按顺序，每步都是 grep 而不是通读）

### 1. 建立基线：文档清单 + 各自最后改动时间

```bash
wc -l docs/*.md README.md | sort -n
for f in docs/*.md README.md; do
  printf "%-40s %s\n" "$f" "$(git log -1 --format=%ad --date=short -- "$f")"
done
```

**最后改动时间明显偏早的文档，就是最可能过期的那几份** —— 优先读它们。
（本轮实测有效：两份 5 天未动的设计文档里确实藏着"文档写了但没实现"的端点。）

### 2. 枚举真实功能面（不要凭记忆）

```bash
# 真实路由（唯一的端点真源）
grep -n '\.GET(\|\.POST(\|\.PUT(\|\.DELETE(\|\.PATCH(' internal/api/router.go

# 真实模型字段（唯一的列真源）
grep -n "^type " internal/model/model.go
# 真实枚举常量
sed -n '/^const (/,/^)/p' internal/model/model.go
```

### 3. 抽样比对：拿「代码里有的」去文档里找

对每个真实端点 / 字段 / 枚举，反向 grep 文档，**找不到就是要补的**：

```bash
for p in "<新端点>" "<新字段>" "<新枚举值>"; do
  printf "\n=== %s ===\n" "$p"; grep -rn "$p" docs/ README.md | head -5
done
```

### 4. 反向比对：拿「文档里写的」去代码里找（最容易漏的一步）

把文档里出现的路径、字段名、环境变量抽出来，逐个到代码里验证存在性。
本轮就是靠这一步抓到 `/steps/{id}/debug`、`/open/plans/{id}/run`、`suite_ids` 三处虚构物：

```bash
for p in "suite_ids" "open/plans" "steps/{id}" "plans/{id}/run" "runs/{id}/steps"; do
  printf "\n=== %s ===\n" "$p"; grep -rn "$p" docs/ README.md | head -5
done
```

### 5. 交叉引用编号必须「先存在、后引用」

代码注释与文档里常见 `（实测 A23）` 这类编号引用。**引用一个不存在的编号是一种静默错误**：
读者去查会查到完全不相干的内容。做法：

```bash
# 先看编号定义处实际有哪些
grep -n "^### A" docs/引擎实测记录.md | tail -12
# 再看谁在引用
grep -rn "A23" docs/ README.md internal/ --include=*.go | grep -v _test
```

⭐ **本轮踩到的真坑**：`A23` 被 `importsvc.go` 注释与 README 引用为「hrp convert 实测」，
但那条**从未写进《引擎实测记录》**；后来另一处新增又占用了 A23，导致所有旧引用指错。
**处理规则：给新结论分配编号前，先确认这个编号没被「已存在的引用」预占**；
若发现"编号被引用但条目缺失"，正确做法是**补写那条缺失的条目**，
而不是让新条目占用它、再去改一堆引用。

### 6. 按 7 类高频失效模式逐份检查

| # | 失效模式 | 怎么查 |
|:---|:---|:---|
| 1 | **文档声称的端点不存在** | 第 4 步的反向 grep + `router.go` |
| 2 | **端点名写错**（草案名 vs 实现名） | 比对 `router.go` 的注册路径 |
| 3 | **数据模型落后**（字段被删/被加、DDL 与 struct 不一致） | 比对 `model.go` 与《数据库设计》DDL |
| 4 | **枚举字典不全**（新枚举没进字典表） | 比对 `const` 块与枚举字典章节 |
| 5 | **配置值写错但"看起来对"**（如 `DISABLE_GA=1` 实际必须字面量 `true`） | 回到实测记录/源码确认取值形式 |
| 6 | **裁剪项被写成已交付** | grep 空目录/占位文件 + 编译器里的"尚未开放"分支 |
| 7 | **内部编号引用指向错误条目** | 第 5 步 |
| 8 | **表名漂移**（只查了"表存在"没查"表名逐字"） | `grep TableName internal/model/model.go` 逐个与文档 DDL 的 `CREATE TABLE` 名对照；有条件时连真实库（sqlite_master）再验一遍。2026-10-31 实踩：文档写 `testcase/teststep/testsuite`，实际是 `test_case/test_step/test_suite`，逃过了只查存在性的上一轮审计。注意区分**不该改**的同名概念：步骤类型枚举 `testcase`、引擎 YAML 键 `teststeps` |

### 7. 收尾

```bash
# 链接校验（docs 内部 .md 引用是否有效）
for f in docs/*.md; do
  while read -r l; do
    case "$l" in http*|"") continue;; esac
    [ -f "docs/$l" ] || echo "缺失: $f -> $l"
  done < <(grep -oh "](\([^)]*\.md\)" "$f" 2>/dev/null | sed 's/](//')
done

git diff --stat
```

提交时按「编号冲突 / 端点类 / 配置类 / 数据模型类 / 验收类」分组写 commit body ——
让 review 的人能一眼看出每类改了什么，而不是一堆"更新文档"。

## 硬性提醒

- **只改文档，不改代码**。审计中发现的代码问题（如 GORM 列默认值与服务层默认值不一致）
  **单独报告给用户定夺**，不要顺手改 —— 用户的约定是「不擅自改动代码」。
- 改 DDL 时注意该项目的约定：**布尔列一律不写 `DEFAULT`**（GORM 会把带默认值的列从
  INSERT 排除，`false` 被静默写成 `true`），string 列 `default:''` 才是安全的。
- **自己刚写的新文档也要审计**。本轮在自查新写的验收清单时，
  发现 3 处"凭印象写"的期望值（策略有 random、调试会留记录、已删成员可从界面构造）全都不准。
- 报告时明确区分「本次已改」与「待用户定夺」，不要把两者混在一段里。
