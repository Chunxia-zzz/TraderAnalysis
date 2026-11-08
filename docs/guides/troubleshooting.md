# 排坑手册（症状 → 原因 → 解法）

> 只收**已经真实踩过**的坑，每条都标明「怎么验证好了」。
> 新增条目请按同一格式：**症状 / 原因 / 解法 / 验证**，并写清适用平台。
> 相关：`docs/guides/ops/README.md`（部署拓扑）、`skills/trader-daily-update/SKILL.md`（日更流程）。

## 速查

| 症状 | 去哪节 |
|---|---|
| bash 里 `grep`/`dirname`/`cat` 报 `command not found` | [1](#1-bash-命令全部-command-not-found) |
| futu 初始化报 `TypeError: expected str, not NoneType` | [2](#2-futu-sdk-报-expected-str-not-nonetype) |
| `npm run dev` 报「拒绝访问」 | [3](#3-npm-run-dev-被拒) |
| PowerShell 执行成功但看不到输出 | [4](#4-powershell-无输出) |
| 端口被占 / 杀了进程还在 | [5](#5-停服务与进程树) |
| 改了代码但行为没变 | [6](#6-改完代码行为没变) |
| `scp` 没报错，线上还是旧数据 | [7](#7-scp-没报错但没生效) |
| 公网 8000 返 502 | [8](#8-公网-8000-返-502) |
| 服务器 `git log` 显示旧 commit | [9](#9-服务器-git-log-停在旧-commit) |
| 重跑 `scan-signals` 后信号数翻倍 | [10](#10-信号数翻倍) |
| 盘中跑出来的 K 线是半截的 | [11](#11-盘中半截-k-线) |
| 回填历史后温度/评分虚高 | [12](#12-回填后温度评分虚高) |
| MA250 / 52 周新高大量为空 | [13](#13-长周期指标大面积为空) |
| 某标的单日 -50% 暴跌 | [14](#14-单日暴跌-复权断层) |
| 晨星显示 58% 折价，实际没那么便宜 | [15](#15-晨星-58-不是折价) |
| 高分标的买完继续跌 | [16](#16-高分标的买完继续跌) |
| `/api/allocation` 的 gap 大得离谱 | [17](#17-allocation-缺口虚高) |
| 今天的温度和上周日报对不上 | [18](#18-温度与历史日报对不上) |

---

## 环境与进程

### 1. bash 命令全部 command not found

**症状**：`grep: command not found`、`dirname: command not found`、`cat: command not found`，但 `ls` 有时还能用。

**原因**：bash 沙箱的 `PATH` 被截断，`/usr/bin` 不在其中。**不要**以为命令没装。

**解法**：每条命令前加一次（版本号自动取当前安装的，勿写死）：

```bash
export PATH="$(ls -d /c/Users/Administrator/.workbuddy/binaries/PortableGit/versions/*/usr/bin 2>/dev/null | tail -1):/c/Windows/System32:/c/Windows:$PATH"
```

**验证**：`which grep dirname cat head` 四个都有输出。

> 历史坑：旧文档写死 `versions/1.2.0`，机器升级到 1.3.0 后该路径失效，照着抄反而必然 `command not found`。

### 2. futu SDK 报 expected str, not NoneType

**症状**：`from futu import OpenQuoteContext` 后初始化抛 `TypeError: expected str, not NoneType`。

**原因**：Windows 下 `APPDATA` 环境变量未传给进程，futu SDK 拼配置路径时拿到 `None`。

**解法**：

```bash
export APPDATA='C:/Users/Administrator/AppData/Roaming'
export appdata='C:/Users/Administrator/AppData/Roaming'
```

**验证**：`python -c "from futu import OpenQuoteContext; print('ok')"` 不再报错。

### 3. npm run dev 被拒

**症状**：前端 `npm run dev` 报「拒绝访问」，或触发沙箱程序黑名单（`wsl.exe`）。

**原因**：npm 脚本会派生 shell 子进程，被沙箱拦截。

**解法**：绕过 npm 直接起 vite：

```bash
cd /f/TraderAnalysisFrontend && node node_modules/vite/bin/vite.js --port 5173 --host
```

**验证**：5173 可访问。**已多次复现，这就是本机固定做法**。

### 4. PowerShell 无输出

**症状**：`powershell -Command "Stop-Process ..."` 返回成功，但看不到任何 stdout。

**原因**：该环境下 PowerShell 不把 stdout 回传给调用方。

**解法**：**杀进程用 PowerShell，验证用 bash**（`netstat -ano | grep :8000`）。不要靠 PowerShell 的输出判断结果。

### 5. 停服务与进程树

**症状**：杀掉 8000 的进程后，5173 还活着；或杀掉 node 后整个宿主卡住。

**原因**：uvicorn/vite 由父进程派生，只杀子进程会留下孤儿；而父进程可能是 `WorkBuddy.exe` 的 node 组件。

**解法**：按进程树杀，**但先确认父进程不是 `WorkBuddy.exe`**：

```bash
taskkill //PID <父PID> //T //F
netstat -ano | grep -E ":8000|:5173"
```

**验证**：两个端口都无监听，且宿主仍正常。

### 6. 改完代码行为没变

**症状**：改了 `market_scorer.py` / `livermore_detector.py`，重启了 `trader-analysis serve`，但接口返回还是旧结果。

**原因**：uvicorn 的 `--reload` **只监听入口模块**，非入口文件改动不会被感知；而且内存里还有 `LIV_CACHE_TTL`（默认 300s）的缓存。

**解法**：按进程树杀掉后端 → 重新起 → 必要时加 `?refresh=true` 绕过 livermore 缓存。

**验证**：在新进程里 `python -c "import ...; print(改过的常量)"`，或看接口返回里是否出现新字段。

---

## 部署

### 7. scp 没报错但没生效

**症状**：`scp data/indicators.db root@...:/opt/trader-analysis/data/` 无任何输出，线上 API 仍返回旧日期。

**原因**：scp 失败时可能静默（权限/沙箱/磁盘满），「无输出」不等于成功。

**解法**：传完必须**回读校验**：

```bash
ssh root@47.106.175.84 "ls -l /opt/trader-analysis/data/indicators.db; md5sum /opt/trader-analysis/data/indicators.db"
md5sum data/indicators.db   # 两边必须一致
```

再打一次公网 API 确认日期前进。**SQLite 每次查询新开连接，覆盖 DB 后无需重启服务。**

### 8. 公网 8000 返 502

**症状**：`http://47.106.175.84:8000/api/...` 502，但 80 端口正常。

**原因**：安全组未放行 8000。服务本身没坏。

**解法**：走 80（nginx 反代到 8000）。注意：**在服务器上 `curl 127.0.0.1/api/...` 会 404**，因为 Host 落到 `default.conf`——这不是故障。

### 9. 服务器 git log 停在旧 commit

**症状**：`git -C /opt/trader-analysis log` 显示的还是几天前的 HEAD，让人以为部署失败。

**原因**：post-receive 钩子用 `--work-tree` 检出，**不推进该目录自己的 HEAD**。

**解法**：**看文件内容或产物时间戳，不看 `git log`**：

```bash
ssh root@47.106.175.84 "grep -n '新函数名' /opt/trader-analysis/src/trader_analysis/xxx.py; systemctl show -p ExecMainStartTimestamp trader-api"
```

---

## 数据

### 10. 信号数翻倍

**症状**：同一天重跑 `scan-signals`，`top_signal_log` / `bottom_signal_log` 行数翻倍，3/3 名单失真。

**原因**：这两张表**没有唯一约束**，插入不去重。`livermore_signal_log` 有 `UNIQUE(code,date,signal_type)` + `INSERT OR REPLACE`，不受影响。

**解法**：重扫前先按 `(code, date)` 删旧行：

```sql
DELETE FROM top_signal_log WHERE date = '2026-10-30';
DELETE FROM bottom_signal_log WHERE date = '2026-10-30';
```

**验证**：`SELECT date, COUNT(*) FROM top_signal_log GROUP BY date` 单日行数与标的数同量级。

### 11. 盘中半截 K 线

**症状**：北京时间 21:30 之后跑 `update`，当天那根日线成交量明显偏小（当日量/前日量 < 1）。

**原因**：美东盘中，当天日线还在走。

**解法**：**代码已拦**（`market_clock.filter_closed_bars`，`1d` 过 16:00、`1w` 过周五 16:00）。
盘中跑只落到上一交易日属**正常**，报告里必须标明「数据日是哪天、是否盘中」。
确需写入可加 `--allow-partial` 或 `TA_ALLOW_PARTIAL_BAR=1`（**不建议**：增量是 `date > last_date`，写进去永不覆盖）。

> ⚠️ 勘误（2026-11-08）：4H 已于本日下线（`specs/002-remove-4h-cycle`），上文原先另有「`4h` 过其结束时刻」一条，
> 现已随功能移除；4H 历史行保留但不参与更新与展示。

### 12. 回填后温度/评分虚高

**症状**：`temperature --backfill N` 或 `score --backfill` 之后，历史中间日的温度/评分比之前高。

**原因**：周线 `date` 记该周**周一**，但 OHLC 整周聚合、周五收盘才成立。旧代码用 `<=` 判断可用性，周一就取到了「周五才成型」的周线 —— 周线前视偏差。**已于 2026-10-31 修复**（`weekly_bar_usable` / `filter_week_closed`）。

**解法**：确认代码包含 `filter_week_closed`（`market_clock.py`），然后重跑 backfill。
**只影响「补算刚结束那一周」**，当天跑当天不受影响。

### 13. 长周期指标大面积为空

**症状**：`ma250`、`high_250`、52 周新高判定大量为 `null`。

**原因**：数据深度不足。**195 只里有约 145 只的日线只有约 119 根**。

**解法**：不要假设有 250 根。用 `has_250_bars` 判断，降级用 `range_high`（近期区间高点）。

### 14. 单日暴跌（复权断层）

**症状**：某标的日线出现单日 −50% 级暴跌，或库里最新价与富途快照对不上。

**原因**：`providers.py` 传 `autype=QFQ`（前复权），但 `daily_update` 是**增量拉取**。QFQ 基准是最新价，拆股/除权后全部历史需重算，增量只追加 → 拆股前价格停在旧基准，形成假断层，进而污染 dd60/RSI/MACD/布林。

**解法**：

```bash
python scripts/refetch_klines.py US.APH HK.07709 ...
```

判别法：找「单日跌幅 > 25% 且量比 > 1.5」的跳变点，再用 `get_market_snapshot` 比对 `last_price`。

---

## 分析与解读

### 15. 晨星 58% 不是折价

**症状**：`ms_discount_pct = 58.2`，被读成「比公允价值低 58%」。

**原因**：公式是 `(fv − close) / close × 100`，分母是**现价**，所以它是**上涨空间**。

**解法**：58.2 = 「还有 58% 上行空间」。真正的溢价率看 `allocation.py` 的 `premium`。

### 16. 高分标的买完继续跌

**症状**：`total_score ≥ 80` 的标的买入后继续下跌，怀疑模型失效。

**原因**：`total_score` 是**纯均值回归**——6 因子全部「越跌分越高」，高分 = 跌得狠，**不代表趋势转好**。而且 SB 榜是**瞬时排序**，不是长期持有名单。

**解法**：结合三件事判断：
1. `ema_ribbon` 方向与 `ribbon_flip`（`to_bear` 数量大 = 空头排列里的深蹲）
2. 单日暴跌推高的高分要打折（财报暴雷会同时拉高评分和风险）
3. `dd60_ok`：60 日跌幅 > 30% 的不碰（3/3 的第一项检查）

### 17. allocation 缺口虚高

**症状**：`/api/allocation` 里 `actual_value` 远小于真实持仓市值，`gap` 大得离谱。

**原因**：`actual_value` **只统计目标清单内的代码**，非目标持仓不计入。

**解法**：读 gap 时明确它是「目标清单内」的缺口，不是总资产缺口；总资产看 `/api/position`。

### 18. 温度与历史日报对不上

**症状**：今天的温度和上周日报里的数字没法比，看起来「突然反转」。

**原因**：2026-10-19 做过**口径镜像反转**（分数越高=越恐慌）。旧 36.8 ↔ 新 63.2 是同一个市场状态。

**解法**：跨期比较**只看建议仓位%**，不比温度绝对值。要换算旧值：`新 = 100 − 旧`。
