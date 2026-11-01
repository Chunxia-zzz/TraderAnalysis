---
name: spec-kit-entry
description: 规范开发入口。用户要「开发功能 / 改需求 / 修 bug / 改代码」时先跑本技能：① 三层体检 spec-kit 工具链（CLI / 项目初始化 / 命令层与扩展），缺哪层补哪层并逐条验证；② 判定本次是「缺陷修复」还是「新需求」，再走对应流程。触发词：开发、加功能、加个页面、改需求、修 bug、这个不对、按钮没反应、数据显示错了、帮我改一下。
license: MIT
compatibility: 需要 Python 3.11+ 与 pip；适用于任意准备使用 spec-kit 的仓库（Windows Git Bash 或 POSIX 均可）
metadata:
  version: "1.0.0"
  origin: 2026-11-01 spec-kit 落地试点的踩坑沉淀
---

# 规范开发入口

> **本技能解决一个问题：不依赖"人记得开口"。**
> 只要调用一次，体检、补齐、验证、分流全在这里完成；不要让用户自己去记 `/speckit-*` 命令。

按顺序执行四步，**不要跳步**。第 1、2 步是"能不能用"，第 3 步是"该用哪条"，第 4 步才是干活。

---

## 第 1 步：三层体检（先查，不要猜）

`spec-kit 已装` 和 `这个项目能用 spec-kit` 是**三件不同的事**，必须分别查。只查 `.specify/` 是错的 ——
`.specify/` 在、但 `.claude/skills/speckit-*` 没了的情况确实会发生（命令层不入库），
此时命令**不可用且不会报错**。

在项目根执行：

```bash
export PATH="$(ls -d /c/Users/Administrator/.workbuddy/binaries/PortableGit/versions/*/usr/bin 2>/dev/null | tail -1):/c/Windows/System32:/c/Windows:$PATH"
# specify.exe 装在 Python 的 Scripts 目录，通常不在 PATH。
# 注意必须用 cygpath 转换：sysconfig 返回的是 C:\... 反斜杠形式，Git Bash 的 PATH 认不了。
export PATH="$(cygpath -u "$(python -c 'import sysconfig; print(sysconfig.get_path("scripts"))')"):$PATH"

echo "--- 1 CLI ---";        specify --version 2>&1 || echo "MISSING"
echo "--- 2 项目 ---";       test -f .specify/memory/constitution.md && echo OK || echo "MISSING"
echo "--- 3 命令层 ---";     ls .claude/skills 2>/dev/null | grep -c '^speckit-' || echo 0
echo "--- 3b bug扩展 ---";   ls .claude/skills 2>/dev/null | grep -c '^speckit-bug-' || echo 0
```

判据（实测基准，2026-11-01）：

| 层 | 通过条件 | 不通过的含义 |
|---|---|---|
| 1 CLI | 输出 `specify 1.x.x` | 本机没装工具链 |
| 2 项目 | `.specify/memory/constitution.md` 存在 | 这个仓库没初始化 |
| 3 命令层 | `speckit-*` 总数 **≥ 10**（基础命令）；装完 bug 扩展为 **13** | init 过但命令层被清掉了（换机器/新 clone） |
| 3b bug 扩展 | 数量 **= 3** | 装过 init 但没装 bug 扩展 → 修 bug 时无路可走 |

同时检查 constitution 是不是**没填的模板**。注意**必须三态判断**：

```bash
if [ ! -f .specify/memory/constitution.md ]; then
  echo "无文件"
elif grep -q '\[PROJECT_NAME\]' .specify/memory/constitution.md; then
  echo "模板未填"
else
  echo "已填"
fi
```

> ⚠️ 不要写成 `grep -q ... && echo 未填 || echo 已填`。文件不存在时 `grep` 也返回非零，
> 会被判成"已填"—— 实测踩过，会在项目根本没初始化的情况下报告 constitution 已就绪。

**三层全绿 → 跳到第 3 步。任何一层红 → 第 2 步。**

---

## 第 2 步：补齐并验证（缺哪层补哪层，不要全量重来）

### 2.1 缺 CLI → 装

官方推荐 `uv tool install specify-cli`。**本机没有 uv，用 pip 等价安装**，不要为此先去装 uv：

```bash
python -m pip install --disable-pip-version-check specify-cli > /tmp/specify-install.log 2>&1
echo "EXIT=$?"; tail -5 /tmp/specify-install.log
```

- **首次约 6 分钟**（要下 cryptography / pywin32，网络慢时更久）。**不要给这条命令接 `| head` / `| tail`，会被 SIGPIPE 打断且装不上。**
- 装完 `specify.exe` 落在 Python 的 Scripts 目录，**通常不在 PATH** —— 用第 1 步那两条 `export PATH` 把它加进来再验证。

### 2.2 缺项目 / 缺命令层 → init

**前置：工作区必须干净**（`git status --porcelain` 无输出）。不干净就先 `git stash` 或开分支，
这是 `--force` 出问题时的回滚保险。

```bash
git status --porcelain
specify init --here --force --non-interactive --integration claude --script sh
```

- `--integration claude` 默认装的是 **skills 不是 commands**，落在 `.claude/skills/speckit-*`，调用写法是 `/speckit-specify`（连字符）。
- 已知安全：实测**不会覆盖已跟踪文件**（`AGENTS.md` 等前后 sha256 一致），但仍要保留上面的前置检查。
- **不要给 init 接管道**，同上会 SIGPIPE。

### 2.3 缺 bug 扩展 → 装

```bash
specify extension add bug
```

装完 `specify extension list` 应能看到 `Bug Triage Workflow`，命令为 3 条。
扩展配置入库在 `.specify/extensions/bug/`，命令层 `.claude/skills/speckit-bug-*` 不入库。

### 2.4 逐条验证（必须真的跑，不能假定成功）

```bash
specify --version                                          # 有版本号
test -f .specify/memory/constitution.md && echo 项目OK      # 文件在
ls .claude/skills | grep -c '^speckit-'                    # ≥ 10（含 bug 扩展为 13）
ls .claude/skills | grep -c '^speckit-bug-'                # = 3
specify extension list | grep -q 'Bug Triage' && echo 扩展OK
```

任何一条不过 → **停下来如实报告哪条没过、为什么**，不要继续往下走假装能用。

---

## 第 3 步：判定走哪条流程

先自己从用户的话里推断，**推不出来就问**。

| 用户表达 | 判定 | 走向 |
|---|---|---|
| 报错、空白、点了没反应、数字/文案不对、A 应该是 B、以前好好的 | **缺陷** | bug 三件套 |
| 新增、加个、支持、能不能做、把 X 改成 Y（新行为） | **新需求** | SDD 六步 |
| 错别字、样式微调、单行 bug、版本号、注释、纯文档措辞 | **豁免** | 直接改 |
| 说不清 / 两种都像 | — | **必须问** |

判断不了时，用一次选择式提问（**不要替用户选流程**，选错的代价比多问一句大得多）：

- 选项 A：修缺陷（行为本该对但不对）
- 选项 B：新需求（要新增或改变行为）
- 选项 C：小改动，直接改

问题里要带上你的推断依据，例如「你说『点进去是空白』，听起来是缺陷；但也可能你想要一个新页面 —— 是哪种？」

---

## 第 4 步：执行对应流程

### 4.1 缺陷 → bug 三件套

```
/speckit-bug-assess "<症状，可粘贴原文或给 issue URL>" slug=<kebab-slug>
/speckit-bug-fix  slug=<slug>
/speckit-bug-test slug=<slug>
```

- slug 用 **ASCII kebab-case**（2~4 词），目录是 `.specify/bugs/<slug>/`。
- 终局结论只有三种：`verified` / `partial` / `failed`。
- **`partial` 或 `failed` 不算修好**，不要向用户报"已修复"。

### 4.2 新需求 → SDD 六步

```
/speckit-specify  →  /speckit-clarify（有歧义才用）  →  /speckit-plan
                  →  /speckit-tasks  →  /speckit-implement  →  /speckit-converge
```

- 目录名用 `--short-name` 保持 **ASCII**，中文留在 spec 正文（中文会让脚本生成中文目录名，Windows 下是编码雷区）。
- **`converge` 有追加任务就再跑一轮 `implement`**，直到报告 Converged。
- 收敛发现属"需要用户决策"的（口径怎么定、要不要改后端），**停下来问**，不要自己拍。

---

## 硬规则（违反过的，都是有代价的）

1. **先判定流程，再建任何文档。** 顺序反了就会出现"5 行改动配 3 份文档 + 25 条任务"（2026-11-01 实测，规格与规模严重失衡）。
2. **"已安装"必须以命令层为准。** 只看 `.specify/` 会把"命令不可用"误判成"能用"。
3. **验证要真跑命令。** 不要说"应该装好了"。
4. **init 之前必须工作区干净。** `--force` 的前提是能回滚。
5. **缺口径/契约类问题，不要自己定。** 那属于产品决策。
6. **跨仓库改动先改被依赖方。** 接口契约以后端为准，前端 spec 只写"消费哪个字段"。

## 本机已知坑（Windows + Git Bash）

| 现象 | 原因 | 处理 |
|---|---|---|
| `specify: command not found` | `.exe` 不在 PATH | 用 `cygpath -u "$(python -c 'import sysconfig; print(sysconfig.get_path("scripts"))')"` 加进 PATH（**直接拼 `C:\...` 无效**） |
| `specify init` 后 `.specify/` 没生成 | 命令接了 `\| head`，SIGPIPE 打断 | 重定向到日志，不接管道 |
| `setup-plan.sh` 退出码 1 | `[safe-delete][SAFE_DELETE_INVALID_PATH]`，Windows 临时文件清理 bug | **无害**，`plan.md` 已生成，继续 |
| `setup-tasks.sh` 没生成 `tasks.md` | 该脚本只把模板内容吐成 JSON | 按模板自己写 `tasks.md` |
| `curl` 访问 localhost 返回 502 | 沙箱设了 `HTTP_PROXY`，把 localhost 也代理了 | 加 `--noproxy '*'` |
| 中文目录名 | 未传 `--short-name` | 一律传 ASCII `--short-name` |

## 汇报格式

做完体检和分流后，用三行向用户报告，不要长篇大论：

```
环境：CLI 1.2.5 ✓ / 项目已初始化 ✓ / 命令层 10 条 ✓ / bug 扩展 3 条 ✓
分流：缺陷（依据：你说"点进去是空白"）→ bug 三件套
下一步：/speckit-bug-assess ... slug=xxx      ← 确认后我就开始
```
