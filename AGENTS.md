# AGENTS.md — TraderAnalysis

> **本文件是跨 agent 的唯一入口。** 任何模型（Codex / Claude Code / Cursor / Gemini / 其他）接手这个仓库，
> 先读完这一份再动手，不要靠猜。
>
> **本文件是操作层** —— 命令、路径、环境坑、目录地图。
> **原则层在 `.specify/memory/constitution.md`**（6 条原则 + 安全边界 + 优先级）。
> 两者冲突时**以 constitution 为准**，并同步修正本文件，不让两份长期打架。
>
> 最后更新：2026-11-01

---

## 0. 开工前 30 秒（命中即执行，不要跳过）

动手改代码前先回答一个问题：**这是缺陷，还是新能力？**

| 情况 | 走哪条 | 产物 |
|---|---|---|
| 行为不对但本该对（报错、数字错、文案错、页面空白） | **bug 三件套** `assess → fix → test` | `.specify/bugs/<slug>/` |
| 要新增能力 / 改数据模型 / 改 API 契约 / 改评分·温度·信号口径 | **SDD 六步** `specify → plan → tasks → implement → converge` | `specs/NNN-<slug>/` |
| 命中豁免清单（文案更正 / 单行 bug / 版本号 / 注释 / 纯文档措辞） | 直接改 | CHANGELOG 记一行 |

- **判断不了就问用户，不要自己选。** 选错流程比不做更糟：5 行改动用完整 SDD 跑过一遍，规格与规模严重不匹配（2026-11-01 教训）。
- **推荐做法**：直接调用 **`spec-kit-entry` 技能**（`skills/spec-kit-entry/SKILL.md`）—— 它会自动做三层体检 + 分流，
  比人记命令可靠。本节的表是它的判定依据摘要，不重复其步骤。
- **跳过这一步的代价**：需求只留在对话里，事后无法核对「当初打算做什么」，也就无法判断实现有没有跑偏。
- 命令是助手技能而非终端命令，用法见 §7。**命令层不入库，换机器要重跑 `specify init` + `specify extension add bug`**，否则命令静默消失。

---

## 1. 这是什么

Futu（富途）量化评分与模拟盘交易系统。核心链路：**Futu OpenD 拉 K 线 → 算指标 → 6 因子评分 → 扫信号 → SQLite → FastAPI → Vue 前端**。

- 后端：Python 3.10+ / FastAPI，代码在 `src/trader_analysis/`
- 前端：Vue 3 + Vite，**独立仓库** `F:\TraderAnalysisFrontend`（不在此仓库内）
- 数据：SQLite 单库 `data/indicators.db`（**不入库**，见 §5）
- 标的池：**195 只**，唯一源是 SQLite `watchlist` 表
- 线上：<http://47.106.175.84/>

## 2. 三条最容易踩错的约束

1. **两套信号体系刻意不合并。**
   `total_score` 是 6 因子**均值回归**（越跌分越高，买超卖）；`livermore_signal_log` 是**关键点突破**（买突破）。
   方向相反，所以利弗莫尔**不并入** `total_score`、不写 `top/bottom_signal_log`，独立落库、独立 API、独立页面（`/livermore`）。
2. **「支撑压力位」≠「利弗莫尔关键点」。** 前者是 Swing Pivot 聚类，后者是平台突破体系，勿混称。
3. **市场温度分数越高 = 越恐慌 = 越该加仓。** 2026-10-19 做过口径反转，940 天历史已镜像迁移。
   看到「高分」不要以为代表强势，也不要把它改回旧口径。

## 3. 目录地图

| 路径 | 是什么 |
|---|---|
| `src/trader_analysis/cli.py` | CLI 入口（`trader-analysis <cmd>`） |
| `src/trader_analysis/futu_strategy/` | 核心：`config` / `storage` / `scorer` / `market_scorer` / `api_server` / `watchlist_storage` / `livermore_detector` / `grid_trader/` |
| `data/indicators.db` | SQLite 主库（15 张表；K 线 / 评分 / 信号 / 标的池）**不入库** |
| `data/target_allocation.json` | 目标仓位配置，**运行时缓存**，页面可改、不入库 |
| `data/_backup/` | 数据库快照，不入库 |
| `docs/` | 文档总入口是 **`docs/README.md`**（按「我要干什么」导航）；分层：`overview/` `guides/` `reference/` `modules/` `history/` |
| `docs/guides/ops/` | 线上 systemd + nginx 配置副本（**改服务器必须回写这里**） |
| `docs/guides/reports-index.md` | 日报索引（正文含账户信息，不入库） |
| `.specify/` | SDD 配置：`memory/constitution.md`（**原则层**）/ `templates/` / `scripts/` |
| `specs/` | **事前意图**：每个 feature 一个 `NNN-<ascii-slug>/`（spec / plan / tasks），见 `specs/README.md` |
| `skills/` | 技能唯一真相源，见 §7 |
| `scripts/` | 运维与一次性脚本；`scripts/agent/` 是 agent 相关工具 |
| `tests/` | pytest，当前 **95 项** |

## 4. clone 后第一件事

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # POSIX: .venv/bin/pip
cp .env.example .env                     # 按需填；.env 永不入库
python scripts/agent/sync_skills.py      # 把 skills/ 物化成各 agent 原生目录，必跑
python scripts/agent/fetch_futu_skills.py  # 可选：需要富途行情/交易脚本时
python -m pip install specify-cli          # 可选：要用 /speckit-* 才装
specify init --here --force --non-interactive --integration claude --script sh   # 重建 speckit 命令层
specify extension add bug                  # 重建缺陷三件套命令（assess / fix / test）
```

`/speckit-*` 命令层落在 `.claude/skills/speckit-*`，**不入库**（第三方生成物，与 `skills/futuapi/` 同类）。
新机器上跑一次上面两条 `specify ...` 即可重建；**入库的是 `.specify/`（含 `extensions/bug/` 配置）与 `specs/`**。
漏跑 `specify extension add bug` 的直接后果：`/speckit-bug-*` 命令消失，而且**不会报错**。

数据库不在仓库里（81 MB 二进制）。空库也能起服务，但标的池会是空的。
重建：装好 OpenD 后 `trader-analysis init --start 2022-06-01`。

## 5. 硬性约定

1. **杀进程用 PowerShell**（`Get-Process | Stop-Process`），不要用 `taskkill` 链式命令。
2. **起服务用 bash**。后端 `trader-analysis serve`（8000），前端在独立仓库起 5173。
3. **Vite 改动后 Ctrl+Shift+R 强刷**，否则看到的是旧 chunk。
4. **本地批量验证通过后才推送**，不要每改一处就部署。
5. **禁用 `git add -A`**。工作区常年有未跟踪的运行产物（DB、日志、缓存），逐个 `git add <path>`。
6. **技能改完必跑** `python scripts/agent/sync_skills.py`，并在日更前置检查里跑一次 `--check`。
7. **红线：以下内容一律不入库** —— 富途 `acc_id`、账户资产金额与持仓明细、`.env` 内容、私钥、任何 token。
   投递前自查：`git diff --cached | grep -iE "acc_id|token|password|secret|BEGIN .*PRIVATE"`。
8. **派生物不入库**：`data/*.db`、`data/_backup/`、`logs/`、`.venv/`、`__pycache__/`。仓库只放能重建它们的东西。
9. **仓位意图不入文档**：目标权重、现货标定区间、分批比例、加仓闸门这类「随时会变的个人想法」，
   属于**可丢弃的运行期状态**，只看 `data/target_allocation.json` 与 `GET /api/allocation`。
   **不要写进 README / `docs/` / `specs/`，做文档审计时也不要把它列为「文档缺失」去补。**
10. **非平凡变更先写 spec**：新增功能 / 改数据模型 / 改 API 契约 / 跨模块重构 / 改评分·温度·信号口径
    → 先落 `specs/NNN-<ascii-slug>/spec.md`，再让 `plan.md` 过一遍 Constitution Check。
    豁免清单与小 bug 路径见 `specs/README.md`；目录名用 `--short-name` 保持 ASCII（中文会生成中文目录名）。
11. **上线只能由流水线执行**（specs/001-deploy-on-green）：`push main` + `check` 绿 → `deploy` job →
    推裸库 → `checkout -f <sha>` → 按需 `pip install` → `systemctl restart trader-api` → 轮询 `/health`。
    **不要**手工 `scp`/覆盖 `/opt/trader-analysis`，也**不要**恢复 `post-receive` 的部署逻辑
    （原版备份在 `post-receive.bak-20261104`，仅作查阅）。
12. **回滚用 sha，不重新构建**：`git --git-dir=/opt/git/trader-analysis.git --work-tree=/opt/trader-analysis
    checkout -f <上一个 sha> && systemctl restart trader-api`。先 `rev-parse HEAD` 确认当前在跑哪一版。
13. **`origin` 只指向 GitHub**：服务器地址已拆成 `deploy` remote。推 `deploy` 只更新裸库、**不再上线**，
    上线唯一入口是 GitHub 上 `deploy` job 变绿。

## 6. 文档与提交规则

- 每次开发结束**统一更新** `docs/history/CHANGELOG.md`、`docs/reference/api.md`、`README.md`，且必须与当前代码**完全一致**；
  不一致就如实标注或修正，不允许"文档先写着"。
- 历史段落不要删改：保留原文 + 加一行 `> ⚠️ 勘误（日期）：…`。项目里已有先例（`docs/modules/watchlist.md` 顶部、`docs/overview/architecture.md` 顶部）。
- 线上配置改完，把 `docs/guides/ops/` 里的副本同步改掉。
- 提交信息用 `feat:` / `fix:` / `docs:` / `chore:` / `refactor:` 前缀。

## 7. 技能索引

**命中触发词时，先读对应文件，再按它的步骤执行。** 不要凭印象自创流程。

| 触发词 | 文件 | 前置检查 |
|---|---|---|
| **开发 / 加功能 / 改需求 / 修 bug / 这个不对 / 帮我改一下** | **`skills/spec-kit-entry/SKILL.md`** | — （技能内含三层体检） |
| 更新行情 / 更新数据 / 跑日更 / 补某天的数据 | `skills/trader-daily-update/SKILL.md` | ✅ 两条 `export`（PATH、APPDATA）+ 确认 OpenD `11111` |
| 检查文档有没有要更新的 / 文档和代码对不上 / XX 文档还准吗 | `skills/doc-code-consistency-audit/SKILL.md` | — |

- 日更技能 24.9 KB，是**实测踩坑得来**的，逐字照做；不要"优化"它的步骤。
- 它包含 9 个子流程：六步日更、归档到资料库、停服务、晨星核对、复权断层核对。
- 技能正文纯 markdown，**不依赖任何产品的技能机制**——读文件即可执行。
- 原生目录（`.claude/skills/` 等）是 `skills/` 的生成物，别改那里。
- **例外**：`.claude/skills/speckit-*` 不是本仓库技能，是 `specify init` 生成的第三方命令层，不入库、不要改。

### Spec-Driven Development 命令（`/speckit-*`）

由 `specify init` 生成，**不属于 `skills/` 体系**。流程与硬约束见 `specs/README.md`，原则见 constitution。

| 命令 | 作用 | 产出 |
|---|---|---|
| `/speckit-specify` | 建 feature 目录 + 写规范 | `specs/NNN-<slug>/spec.md` |
| `/speckit-clarify` | 需求有歧义时消歧（可选） | 更新 `spec.md` |
| `/speckit-plan` | 技术方案 + **Constitution Check** | `plan.md` |
| `/speckit-tasks` | 拆成可执行任务 | `tasks.md` |
| `/speckit-implement` | 写代码 | 代码 + 勾选 tasks |
| `/speckit-converge` | 找代码与规范的剩余差距 | 追加 tasks，反复到 Converged |
| `/speckit-analyze` / `/speckit-checklist` | 可选质量门 | 报告 |

**缺陷修复走另一条路（bug 扩展，已安装）** —— 修 bug **不要**套上面 6 步：

| 命令 | 作用 | 产出 |
|---|---|---|
| `/speckit-bug-assess` | 评估缺陷（粘贴文本或 issue URL），定位可疑代码、判定严重性 | `.specify/bugs/<slug>/assessment.md` |
| `/speckit-bug-fix` | 按评估结论修复并记录改了什么 | 代码改动 |
| `/speckit-bug-test` | 验证缺陷是否真的解决 | 验证报告，结论为 `verified` / `partial` / `failed` |

**判定**：行为不对但本该对 → 缺陷，走 bug 三件套；要新增能力 → 走 SDD。**缺少验证不算修好。**

**触发词**：写 spec / 规划某个功能 / 这个改动要不要先写规范 / 检查实现符不符合规范。

> 注意：constitution 是**原则层**，本文件是操作层。改 constitution 必须在 CHANGELOG 记一行并说明**理由** ——
> 它会参与后续每一次 `plan` 的判定，随手改一句等于悄悄放宽了所有未来的约束。

## 8. Windows 环境坑

1. **bash 沙箱 PATH 会损坏** → `grep`/`dirname`/`cat`/`head` 报 `command not found`。每条命令前加：

   ```bash
   export PATH="$(ls -d /c/Users/Administrator/.workbuddy/binaries/PortableGit/versions/*/usr/bin 2>/dev/null | tail -1):/c/Windows/System32:/c/Windows:$PATH"
   ```

   不要写死版本号（历史教训：写死 1.2.0，升级到 1.3.0 后失效）。

2. **futu SDK 需要 `APPDATA`**，否则 `TypeError: expected str, not NoneType`：

   ```bash
   export APPDATA='C:/Users/Administrator/AppData/Roaming'
   export appdata='C:/Users/Administrator/AppData/Roaming'
   ```

3. **北京时间 21:30 前跑，拿到的是上一交易日数据**；之后跑是美东盘中。
   代码已用 `market_clock.filter_closed_bars` 丢弃未收盘 K 线，盘中跑只落到上一交易日属**正常**。
4. **端口占用**：8000 / 5173 残留进程先按约定 1 杀掉。
5. **不要在 Windows 下建 symlink**（需管理员）。技能用目录联结点（`mklink /J`），由同步脚本处理。

## 9. 索引：想找什么去哪

| 想知道 | 去 |
|---|---|
| 不知道去哪找 | **`docs/README.md`**（按目的导航的索引） |
| 改了哪些东西、为什么改 | `docs/history/CHANGELOG.md`（最新在最上） |
| 某个接口的入参出参 | `docs/reference/api.md` |
| 数据库表结构 | `docs/reference/storage.md` |
| 评分/指标/温度/标的池等模块的设计 | `docs/modules/`（文件名即模块名） |
| **遇到报错 / 数据不对 / 部署没生效** | **`docs/guides/troubleshooting.md`**（18 条症状→原因→解法） |
| 线上怎么部署、怎么核验 | `docs/guides/ops/README.md` |
| 日报在哪 | `docs/guides/reports-index.md` |
| **什么能做什么不能做** | **`.specify/memory/constitution.md`**（原则层；与本文件冲突时以它为准） |
| 某个功能当初要做什么 | `specs/<NNN-slug>/spec.md`（事前意图）——现状仍看 `docs/` |
| 新功能该怎么走流程 | `specs/README.md` + §7 的 `/speckit-*` 表 |
| 日更怎么做 | `skills/trader-daily-update/SKILL.md` |
| 标的池怎么管 | `README.md` + `src/trader_analysis/futu_strategy/watchlist_storage.py` |

**核验线上部署时不要 `git -C /opt/trader-analysis log`**：那个目录里的 `.git` 是历史遗留的旧 clone，
既不随部署推进、也不反映现状。要查当前版本用
`git --git-dir=/opt/git/trader-analysis.git rev-parse HEAD`，或直接看接口返回 / 文件内容。

## 10. 常用命令

```bash
trader-analysis serve              # 起 API（8000）
trader-analysis update             # 增量拉 K 线（需 OpenD，约 6–9 分钟）
trader-analysis temperature        # 市场温度（支持 --backfill N）
trader-analysis score              # 个股评分（不依赖 OpenD）
trader-analysis scan-signals       # 扫顶/底/EMA/利弗莫尔信号
trader-analysis livermore --persist
pytest -q                          # 全量测试

# ── 线上发布（由流水线执行，这里只用于核对/应急）──
git push origin main               # 只推 GitHub；check 绿后自动 deploy
ssh root@47.106.175.84 'git --git-dir=/opt/git/trader-analysis.git rev-parse HEAD'      # 线上在跑哪个 sha
curl -s http://47.106.175.84/health                                                     # 健康检查

# 回滚（先确认上一个 sha）
ssh root@47.106.175.84 'git --git-dir=/opt/git/trader-analysis.git --work-tree=/opt/trader-analysis \
  checkout -f <sha> && systemctl restart trader-api'
```

`migrate-watchlist` 与 `data/watchlist.json` **已于 2026-11-01 删除**，不要再找它们。
标的池请走 `POST/PATCH/DELETE /api/watchlist`。
