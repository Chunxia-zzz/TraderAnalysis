# AGENTS.md — TraderAnalysis

> **本文件是跨 agent 的唯一入口。** 任何模型（Codex / Claude Code / Cursor / Gemini / 其他）接手这个仓库，
> 先读完这一份再动手，不要靠猜。
> 最后更新：2026-11-01

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
| `docs/` | `CHANGELOG.md`（必读）、`api.md`、`futu_strategy_docs/`（设计文档） |
| `docs/ops/` | 线上 systemd + nginx 配置副本（**改服务器必须回写这里**） |
| `docs/reports/INDEX.md` | 日报索引（正文含账户信息，不入库） |
| `skills/` | 技能唯一真相源，见 §7 |
| `scripts/` | 运维与一次性脚本；`scripts/agent/` 是 agent 相关工具 |
| `tests/` | pytest，当前 **97 项** |

## 4. clone 后第一件事

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # POSIX: .venv/bin/pip
cp .env.example .env                     # 按需填；.env 永不入库
python scripts/agent/sync_skills.py      # 把 skills/ 物化成各 agent 原生目录，必跑
python scripts/agent/fetch_futu_skills.py  # 可选：需要富途行情/交易脚本时
```

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

## 6. 文档与提交规则

- 每次开发结束**统一更新** `docs/CHANGELOG.md`、`docs/api.md`、`README.md`，且必须与当前代码**完全一致**；
  不一致就如实标注或修正，不允许"文档先写着"。
- 历史段落不要删改：保留原文 + 加一行 `> ⚠️ 勘误（日期）：…`。项目里已有先例（`docs/futu_strategy_docs/.../README.md`）。
- 线上配置改完，把 `docs/ops/` 里的副本同步改掉。
- 提交信息用 `feat:` / `fix:` / `docs:` / `chore:` / `refactor:` 前缀。

## 7. 技能索引

**命中触发词时，先读对应文件，再按它的步骤执行。** 不要凭印象自创流程。

| 触发词 | 文件 | 前置检查 |
|---|---|---|
| 更新行情 / 更新数据 / 跑日更 / 补某天的数据 | `skills/trader-daily-update/SKILL.md` | ✅ 两条 `export`（PATH、APPDATA）+ 确认 OpenD `11111` |
| 检查文档有没有要更新的 / 文档和代码对不上 / XX 文档还准吗 | `skills/doc-code-consistency-audit/SKILL.md` | — |

- 日更技能 24.9 KB，是**实测踩坑得来**的，逐字照做；不要"优化"它的步骤。
- 它包含 9 个子流程：六步日更、归档到资料库、停服务、晨星核对、复权断层核对。
- 技能正文纯 markdown，**不依赖任何产品的技能机制**——读文件即可执行。
- 原生目录（`.claude/skills/` 等）是 `skills/` 的生成物，别改那里。

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
| 改了哪些东西、为什么改 | `docs/CHANGELOG.md`（最新在最上） |
| 某个接口的入参出参 | `docs/api.md` |
| 评分/指标/存储的设计 | `docs/futu_strategy_docs/futu_strategy_docs/` |
| 线上怎么部署、怎么核验 | `docs/ops/README.md` |
| 日报在哪 | `docs/reports/INDEX.md` |
| 日更怎么做 | `skills/trader-daily-update/SKILL.md` |
| 标的池怎么管 | `README.md` + `src/trader_analysis/futu_strategy/watchlist_storage.py` |

**核验线上部署时不要看服务器的 `git log`**：post-receive 用 `--work-tree` 检出，不推进该目录的 HEAD，
`git -C /opt/trader-analysis log` 永远是旧 commit。要看**文件内容**或接口返回。

## 10. 常用命令

```bash
trader-analysis serve              # 起 API（8000）
trader-analysis update             # 增量拉 K 线（需 OpenD，约 6–9 分钟）
trader-analysis temperature        # 市场温度（支持 --backfill N）
trader-analysis score              # 个股评分（不依赖 OpenD）
trader-analysis scan-signals       # 扫顶/底/EMA/利弗莫尔信号
trader-analysis livermore --persist
pytest -q                          # 全量测试
```

`migrate-watchlist` 与 `data/watchlist.json` **已于 2026-11-01 删除**，不要再找它们。
标的池请走 `POST/PATCH/DELETE /api/watchlist`。
