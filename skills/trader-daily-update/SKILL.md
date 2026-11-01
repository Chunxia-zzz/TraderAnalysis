---
name: trader-daily-update
description: TraderAnalysis 量化系统的「更新行情」日常流程。当用户说"更新行情"、"更新数据"、"跑一下日更"，或需要补拉某个交易日的行情并刷新评分/信号/线上部署时使用。涵盖 Futu OpenD 增量 K 线 → 市场温度 → 个股评分 → 信号扫描 → 同步线上 → 启动本地前后端的完整 6 步，并包含 Windows/bash 环境坑的确定性修复方式。
---

# TraderAnalysis 更新行情

## 适用场景

- 用户说「更新行情」「更新数据」「跑日更」
- 用户说「继续更新昨天的行情」「补上某天的数据」
- 需要刷新市场温度 / 评分 / 信号并部署到线上

## 关键路径与端口

| 项 | 值 |
|---|---|
| 后端项目 | `F:\TraderAnalysis` |
| 前端项目 | `F:\TraderAnalysisFrontend`（**不在后端目录内**） |
| 数据库 | `F:\TraderAnalysis\data\indicators.db` |
| Python | `F:\TraderAnalysis\.venv\Scripts\python.exe` |
| OpenD | `127.0.0.1:11111` |
| 本地后端 / 前端 | 8000 / 5173 |
| 线上站点 | `http://47.106.175.84/`（80 端口，nginx 反代到 8000） |
| 线上目录 | `root@47.106.175.84:/opt/trader-analysis` |
| 线上服务 | systemd `trader-api.service` |

> 📌 **路径口径**：上表是本机（Windows）的绝对路径。**仓库内引用一律以仓库根为基准**
> （如 `skills/…`、`data/indicators.db`、`.venv/Scripts/python.exe`），换机器时只改上表，正文不动。
> 运维配置副本见 `docs/guides/ops/`。

## 前置检查（每次必做）

1. **PATH 修复** —— bash 沙箱的 PATH 会损坏，`grep`/`dirname`/`cat`/`head` 等会报 `command not found`。**每条命令前都加上**：

```bash
# 自动取当前安装的 PortableGit 版本：不要写死版本号（原写 1.2.0，升级到 1.3.0 后该路径已失效）
export PATH="$(ls -d /c/Users/Administrator/.workbuddy/binaries/PortableGit/versions/*/usr/bin 2>/dev/null | tail -1):/c/Windows/System32:/c/Windows:$PATH"
```

2. **APPDATA 修复** —— futu SDK 初始化需要，否则报 `TypeError: expected str, not NoneType`：

```bash
export APPDATA='C:/Users/Administrator/AppData/Roaming'
export appdata='C:/Users/Administrator/AppData/Roaming'
```

3. **确认 OpenD 在跑**：`netstat -ano | grep ':11111'`
4. **确认当前数据日期**，判断要补**哪几天** —— 隔多日未跑会一次性补齐多个交易日（如 9/24 跑补齐了 9/22 + 9/23，update 日志里会逐日输出「新增 N 根」）。**日志文件按执行当日日期命名**（`2026-09-24.md`），不是数据日期：

```bash
.venv/Scripts/python.exe -c "
import sqlite3
c=sqlite3.connect('data/indicators.db')
print(c.execute(\"select date,count(*) from kline_indicators where ktype='1d' and date>='2026-09-01' group by date order by date\").fetchall())
"
```

**注意交易时段**：北京时间 21:30 前跑，拿到的是上一交易日数据。例如 9/17 21:00 跑只能拿到 9/16；要拿 9/17 必须等 9/18 白天跑。

**⚠️ 21:30 之后跑 = 美东盘中**：北京时间 21:30 之后，当天那根日线还在走。
**2026-10-17 起代码会自动丢掉这根**（`market_clock.filter_closed_bars`，见下），
所以拿着「上一个完整交易日」的结论，报告里**必须标明数据日是哪天、是否盘中**。
自查库里有没有半截数据 —— **比对当日 volume 与前一交易日**，明显小于 1 即为半截：

```bash
.venv/Scripts/python.exe -c "
import sqlite3;c=sqlite3.connect('data/indicators.db')
for code in ['US.SPY','US.QQQ','US.NVDA']:
    v=[r[0] for r in c.execute(\"select volume from kline_indicators where ktype='1d' and (code=? or code=?) and date>='2026-10-15' order by date\",(code,code.replace('US.','')))]
    print(code, v, '比值', round(v[1]/v[0],2) if len(v)>1 and v[0] else '-')
"
```

10/17 实测比值：SPY 0.44 / QQQ 0.55 / AAPL 0.70 / AVGO 0.37 / YUMC 0.32 → 明确是盘中。

**✅ 2026-10-17 起：盘中跑已经安全了（代码层已兜住，不必再手工删表）**

`update` 在写入前会调用 `market_clock.filter_closed_bars()`，**丢掉尚未收盘的 K 线**：

| 周期 | 视为已收盘的条件（该市场本地时间） |
|---|---|
| `1d` | 已过当日 **16:00** |
| `1w`（`date`=该周周一） | 已过当周**周五 16:00** |
| `4h`（`date`=K 线**结束**时刻） | 已过该时刻 |

所以北京时间 21:30 之后跑 `update`，DB 最新交易日会**自动停在「上一个完整交易日」**，
日志末尾会打一行 `⏭ 已跳过 N 根尚未收盘的 K 线（1d/1w/4h）`。这就是**预期行为，不是故障**。

- 判别「库里有没有半截 K 线」仍然看**量比**（下面是通用自查脚本，比值明显 <1 就是半截）
- 需要强制写入盘中那根（调试/补偿）时：`update --allow-partial` 或 `TA_ALLOW_PARTIAL_BAR=1`
- **改动 `market_clock.py` 后必跑回归**：`python scripts/verify_market_clock_live.py`（需 OpenD，
  跑真实 `_update_ktype` + 临时 DB 副本 + 注入盘中时刻，2026-10-17 实测 **35/35**）
- **已核实边界**：半日市（感恩节次日/平安夜）4H 标签是 `13:00` 故准时入库，`1d` 仍等 16:00 → 晚 3 小时（安全）；
  同一时刻**美股拦、港股放行**是时区逻辑正确的反证

```bash
.venv/Scripts/python.exe -c "
import sqlite3;c=sqlite3.connect('data/indicators.db')
for code in ['US.SPY','US.QQQ','US.NVDA']:
    v=[r[0] for r in c.execute(\"select volume from kline_indicators where ktype='1d' and (code=? or code=?) and date>='2026-10-15' order by date\",(code,code.replace('US.','')))]
    print(code, v, '比值', round(v[1]/v[0],2) if len(v)>1 and v[0] else '-')
"
```

> 🟡 **历史背景（已由代码解决，保留以防万一）**
>
> 在守卫上线前，增量过滤是 **`date > last_date`（严格大于）**，**已写入的那根永远不会被覆盖**——
> 当天盘中跑过、次日再跑 `update` 也修不回来（日志满屏「1d 无新增数据」），只能手工删行重拉：
>
> ```bash
> # 仅当受守卫保护之前写入了半截数据、或用了 --allow-partial 误写时才需要
> delete from kline_indicators where ktype='1d' and date='<X>'
> delete from kline_indicators where ktype='1w' and date='<该周周一>'
> delete from kline_indicators where ktype='4h' and date>='<X>'
> # 再 update → temperature --backfill 4 → score --backfill 4
> # → 删 top/bottom_signal_log 该日及之后旧行 → scan-signals --backfill N → livermore --backfill 1
> ```
>
> 10/17 实测：删 1d 192 + 1w 192 + 4h 342 行后重拉，量比 0.44 → 1.49，温度 **40.6 → 36.8**、强买 **22 → 33**。
> ⚠️ **周线也必须一起删**：那根「本周」周线同样是半截的。
>
> ⚠️ **`update` 运行期间绝对不要连 DB 查询**（哪怕只读）：连接不关会触发 `database is locked`，
> 10/17 因此让**连续 20 只标的**更新失败（`US.VRTX` 起到 `US.YUMC`）。要查就等它跑完。

## 六步流程

### ① update —— 增量拉 K 线（约 6–9 分钟）

必须**后台运行**，前台会被 SIGTERM 截断。

```bash
cd /f/TraderAnalysis && .venv/Scripts/python.exe -m trader_analysis update > /tmp/upd.log 2>&1
```

用 `run_in_background: true` 启动，再用 TaskOutput 阻塞等待（timeout 600000）。完成后核对日志尾部出现「增量更新完成，连接已关闭」且日线新增日期正确。

### ②③④ 温度 / 评分 / 信号（串联，约 2–5 分钟）

```bash
cd /f/TraderAnalysis
echo "########## TEMPERATURE ##########" > /tmp/steps.log
.venv/Scripts/python.exe -m trader_analysis temperature >> /tmp/steps.log 2>&1
echo "########## SCORE ##########" >> /tmp/steps.log
.venv/Scripts/python.exe -m trader_analysis score >> /tmp/steps.log 2>&1
echo "########## SCAN-SIGNALS ##########" >> /tmp/steps.log
.venv/Scripts/python.exe -m trader_analysis scan-signals >> /tmp/steps.log 2>&1
echo "########## ALL DONE ##########" >> /tmp/steps.log
```

同样后台 + TaskOutput 等待。用 `sed -n '/TEMPERATURE/,/SCORE/p' /tmp/steps.log` 分段查看结果。

`scan-signals` 是增量补算（从各标的信号表 MAX(date) 之后），无需 `--backfill`。

> ⚠️ **补多日时的重要差异（10/6 实测）**：一次补 6 个交易日时，
> - `score` 会**逐日写入全部日期**（本次 1149 条 = 6 天 × 192）
> - `temperature` **只写最新交易日一行**，中间日（如 9/28~10/2）的 `market_score` 为**空**
>
> ✅ **中间日可以用 `--backfill` 补出来（10/17 实测）**，不必接受「只有两个点」：
>
> ```bash
> .venv/Scripts/python.exe -m trader_analysis temperature --backfill 4   # 从 K 线回溯补最近 4 天
> ```
>
> 10/17 用 `--backfill 4` 一次补出 10/13~10/16 四行，温度趋势立刻完整
> （74.8 → 62.1 → 47.8 → 47.3 → 40.6）。**已验证确定性**：回溯后最新日的值与首次计算完全一致（40.6 / 73.5%）。
>
> ⚠️ **回溯会改 DB → 必须重新 scp 一次**（10/17 因此同步了两次：流程后一次、回溯后一次）。

### ⑤ 同步线上 + 验证

scp 需要读 `.ssh` 密钥，**必须加 `dangerouslyDisableSandbox: true`**：

```bash
scp -o StrictHostKeyChecking=no /f/TraderAnalysis/data/indicators.db \
    root@47.106.175.84:/opt/trader-analysis/data/indicators.db
```

**必须回读验证**（scp 曾静默失败）：

1. 比对本地与线上 bytes 是否一致
2. 请求 `http://47.106.175.84/api/market-temperature`，确认返回的是新日期

SQLite 每次查询新开连接，**覆盖 DB 后无需重启 API**。

> ⚠️ **不要直连公网 8000 端口验证**（会返回 502，云安全组未开放）。一律走 80 端口。

### ⑥ 启动本地服务

```bash
# 后端（后台）
cd /f/TraderAnalysis && .venv/Scripts/python.exe -m trader_analysis serve > /tmp/be.log 2>&1
# 前端（后台）
cd /f/TraderAnalysisFrontend && npm run dev > /tmp/fe.log 2>&1
```

启动后 `netstat -ano | grep 'LISTENING' | grep -E ':8000|:5173'` 确认双端口监听。

### 归档 —— 写进资料库空间（每次日更必做）

项目空间：`amo3KT37smg61B4NxXioH5`（「交易信号永续项目 · TraderAnalysis」）

| 目标 | nodeId |
|---|---|
| `01 每日日报` | `4BgHP4FXxMwztC7aUaY57V` |
| `02 信号台账`（表「每日信号台账」） | `QI8Ansx2e0x7PYMyXWOwwc` |
| `04 复盘与迭代` | `lR9UZl1QeUYpVOjeGsvQU0` |

```bash
SK="F:/workbuddy/resources/app.asar.unpacked/resources/plugins/workbuddy-builtin/skills/library"
PY="C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe"
# 1) 日报（--content-file 指向写好的 md）
"$PY" "$SK/doc/create_doc.py" --title "YYYY-MM-DD 日更报告" \
  --space-id amo3KT37smg61B4NxXioH5 --parent-id 4BgHP4FXxMwztC7aUaY57V --content-file <md路径>
# 2) 台账加一行（字段：日期/市场温度/建议仓位%/强买数/买入数/3/3通过/结构/关键动作/日报）
"$PY" "$SK/database/batch_add_database_records.py" --database-id QI8Ansx2e0x7PYMyXWOwwc --records "$REC"
# 3) 必做回读（success=true 不等于真落库）
"$PY" "$SK/database/get_database_record.py" --database-id QI8Ansx2e0x7PYMyXWOwwc --record-id <rid>
```

**只放结论，不镜像代码**：代码以 Git 为准、行情原始数据在 DB；空间负责跨会话留存的结论与决策。

### ⑦ 停止服务（用户说「停掉后台任务」「要换项目了」时）

**必须按进程树杀，只杀 PID 会留下 npm / uvicorn reloader 父进程成为孤儿。**

进程链形态（Windows）：

```
bash.exe → python.exe(父) → python.exe(uvicorn) → python.exe(worker)     # 后端
bash.exe → node.exe(npm)  → cmd.exe          → node.exe(vite)            # 前端
```

步骤：

1. `netstat -ano | grep 'LISTENING' | grep -E ':8000|:5173'` 拿到**监听端口**的 PID
2. `tasklist | grep -i -E 'node|python'` 列出全部候选进程
3. **先确认归属再杀** —— 用下面的 ctypes 脚本读进程树，看父进程是谁。**父进程是 `WorkBuddy.exe` 的 node 进程属宿主自身组件（MCP 服务等），绝不能杀**
4. `taskkill //PID <父PID> //T //F`（`//T` 杀整棵树，Git Bash 里参数要双斜杠）
5. 复核 `netstat` 确认端口已释放

读进程树的临时脚本（用完即删）：

```python
import ctypes
from ctypes import wintypes
class PROCESSENTRY32(ctypes.Structure):
    _fields_=[("dwSize",wintypes.DWORD),("cntUsage",wintypes.DWORD),("th32ProcessID",wintypes.DWORD),
               ("th32DefaultHeapID",ctypes.POINTER(ctypes.c_ulong)),("th32ModuleID",wintypes.DWORD),
               ("cntThreads",wintypes.DWORD),("th32ParentProcessID",wintypes.DWORD),
               ("pcPriClassBase",ctypes.c_long),("dwFlags",wintypes.DWORD),("szExeFile",ctypes.c_char*260)]
k32=ctypes.windll.kernel32
snap=k32.CreateToolhelp32Snapshot(0x00000002,0)
pe=PROCESSENTRY32(); pe.dwSize=ctypes.sizeof(PROCESSENTRY32); procs={}
if k32.Process32First(snap,ctypes.byref(pe)):
    while True:
        procs[pe.th32ProcessID]=(pe.th32ParentProcessID, pe.szExeFile.decode('gbk','ignore'))
        if not k32.Process32Next(snap,ctypes.byref(pe)): break
for pid,(ppid,name) in sorted(procs.items()):
    if name.lower() in ('python.exe','node.exe'):
        print(pid, ppid, name)
```

> 注：本项目约定「杀进程用 PowerShell」，但**本机 PowerShell 工具当前不返回 stdout**，无法验证结果。改用 bash + `taskkill` 更可靠。

### ⑧ 晨星公允价值核对 / 刷新（可选，建议每月一次，或用户说「核对晨星估值」时）

晨星公允价值存在 `watchlist.morningstar_fair_value`，**不会随日更自动更新**，久不刷新会陈旧（2026-08-20 的旧值一直用到 10-11，导致 33% 的标的偏差 >1%、3 只低估/高估方向翻转）。

**前置**：OpenD 必须在跑。若 11111 无监听，启动 `C:\Users\Administrator\AppData\Roaming\Futu_OpenD\Futu_OpenD.exe`（约 5 秒后监听；`reg.exe` 被沙箱黑名单禁用，用桌面 `Futu OpenD.lnk` 解析路径）。

```bash
export APPDATA='C:/Users/Administrator/AppData/Roaming'; export appdata='C:/Users/Administrator/AppData/Roaming'
cd /f/TraderAnalysis
.venv/Scripts/python.exe -u scripts/audit_morningstar.py              # 抽样核对 18 只（快，只读）
.venv/Scripts/python.exe -u scripts/audit_morningstar.py --all        # 全量核对 170 只（约 10 分钟，只读）
cp data/indicators.db data/indicators.db.bak-$(date +%Y%m%d)-preMSFix # 刷新前必须备份
.venv/Scripts/python.exe -u scripts/audit_morningstar.py --all --fix  # 全量刷新写回（约 11 分钟）
```

刷新后 → scp 同步线上 + 公网 API 回读验证。

> ✅ **刷新晨星不需要重跑 `score`**：`scorer.py` 的 WEIGHTS 全是技术因子（weekly_rsi / daily_macd_pct / boll_position / daily_rsi / weekly_macd_pct / drawdown），**不含晨星**。
> 晨星只影响 ①`/api/scores/overview` 的 3/3 检查里「晨星低估」条件（`close < ms`）②`/api/allocation` 的 level 判定（`close > ms` → expensive；`close < ms` 且 score≥80 → strong_buy；否则 score≥75 或 rsi<40 或空间>10% → buy，否则 watch）。
> 刷新只需 **scp 同步 DB**，`score_results` 不受影响。

> ⚠️ **口径陷阱（报告时别读错）**：`ms_discount_pct` = `(晨星公允价值 − 现价) / 现价 × 100`，是**「上涨空间%」不是折价率**。TMUS 显示 58.2% 表示"还有 58% 上行空间"，不是"比公允价值低 58%"。

底层 API 脚本在 `skills/futuapi/scripts/quote/`（**第三方技能，不入库**；首次需跑 `python scripts/agent/fetch_futu_skills.py` 从富途官方包拉取）：
`get_research_morningstar_report.py`（晨星公允价值/星级/护城河）、`get_research_analyst_consensus.py`（分析师目标价）。晨星接口限频：每 30 秒最多 30 次。

> ℹ️ `watchlist.analyst_target_mean`（前端「分析师目标」卡片用）= 上述脚本 `data.average`，同样**不随日更更新**，且**不参与评分/3-3 检查/加仓建议**，优先级低于晨星。

### ⑨ K 线复权断层核对 / 修复（发现异常暴跌时）

**症状**：某标的日线出现单日 −50% 级别的暴跌，或库中 K 线最新价与 Futu 实时快照对不上。

**根因**：`providers.py:150/165` 传了 `autype=AuType.QFQ`（前复权），但 `daily_update.run_update()` 是**增量拉取**。
QFQ 的复权基准是「最新价」——每次除权后**全部历史都需重算**，增量只追加新数据 → 拆股前的价格停在**旧基准**，库里留下假断层，
进而污染 dd60 / RSI / MACD / 布林，甚至翻转 `dd60_ok` 的 3/3 判定。

**① 定位**：
```bash
cd /f/TraderAnalysis && .venv/Scripts/python.exe -c "
import sqlite3
from collections import defaultdict
c=sqlite3.connect('data/indicators.db')
g=defaultdict(list)
for code,d,cl in c.execute(\"select code,date,close from kline_indicators where ktype='1d' order by code,date\"):
    g[code].append((d,cl))
for code,arr in g.items():
    for i in range(1,len(arr)):
        if arr[i-1][1] and (arr[i][1]-arr[i-1][1])/arr[i-1][1] < -0.25:
            print(code, arr[i][0], arr[i-1][1], '->', arr[i][1])
"
# 再与实时快照比对确认（last_price 应等于重拉后的值，而非库里的旧值）
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'src')
from trader_analysis.futu_strategy import config
from futu import OpenQuoteContext
ctx=OpenQuoteContext(host=config.OPEND_HOST, port=config.OPEND_PORT)
print(ctx.get_market_snapshot(['US.APH','US.GDXU'])[1])
ctx.close()"
```

**② 修复**：
```bash
cp data/indicators.db data/indicators.db.bak-$(date +%Y%m%d)-preKlineFix   # 必须备份（重拉会 DELETE 旧行）
.venv/Scripts/python.exe scripts/refetch_klines.py --dry-run US.APH        # 先看范围
.venv/Scripts/python.exe scripts/refetch_klines.py US.APH HK.07709 US.KORU US.SOXL US.GDXU
.venv/Scripts/python.exe -m trader_analysis score --backfill 5             # K 线变了，评分必须重算
# 若该标的有信号记录：必须先删再算（信号表无唯一约束，重复跑会翻倍）
.venv/Scripts/python.exe -c "
import sqlite3
c=sqlite3.connect('data/indicators.db')
for t in ('top_signal_log','bottom_signal_log'):
    print(t, c.execute(f\"delete from {t} where code='US.APH' and date>='2026-09-01'\").rowcount)
c.commit()"
.venv/Scripts/python.exe -m trader_analysis scan-signals --codes US.APH --backfill 28
# → scp 同步线上 + 公网 API 验证
```

**2026-10-12 已修 5 只**：US.APH / HK.07709 / US.KORU / US.SOXL / **US.GDXU**。
修复后 dd60：APH −49.3%→−1.6% / 07709 −79.7%→−41.5% / KORU −98.5%→−26.2% / SOXL −59.9%→−14.9% / **GDXU −2.9%→−45.2%（用户 24% 持仓，旧库虚高 45%）**。
判别依据：`get_market_snapshot` 的 `last_price` 与重拉后完全一致 → 旧库才是错的。

> ⚠️ Futu **不传 `start` 时只返回最近 250 根**，`max_count` 被忽略。要更长历史必须传 `start`。
> 本扫描阈值 25%，会漏掉 5:4（−20%）等小比例拆股；彻底兜底需全池重拉（约 15-20 分钟）。

## 结果分析

### 拉取信号池（走本地 API，已算好 3/3 check）

```bash
.venv/Scripts/python.exe -c "
import urllib.request, json
with urllib.request.urlopen('http://127.0.0.1:8000/api/scores/overview', timeout=90) as r:
    d=json.loads(r.read().decode())
print('date=', d['date'], 'summary=', d['summary'])
for grp in ['strong_buy','buy']:
    for s in d[grp]:
        print(s['code'], s['total_score'], s['close'], s['dd60_pct'], s['dd60_ok'], s.get('ms_discount_pct'), s['ema_ribbon'], s.get('ribbon_flip'))
"
```

### 必须交叉比对的固定清单

- **实盘持仓**：YUMC、AVGO、CRWV、TSM、RKLB、INTC（用户核心持仓）
- **永久组合**：AAPL/MSFT/AMZN/GOOGL/NVDA/META/TSLA + AVGO/TSM/ASML/INTC + XLV/XLE/XLF + GDX/GLD + IBIT/MSTR/CRCL
- **大盘**：SPY、QQQ

### 现货换算（两点线性标定）

- **黄金**：GLD 363 = 4000，GLD 430 = 4600 → `现货 = 4000 + (GLD - 363) × 600/67`
- **比特币**：IBIT 33 = 58000，IBIT 45 = 81000 → `现货 = 58000 + (IBIT - 33) × 23000/12`
- **IBIT 超过 45 即已突破目标区间上沿，应提示暂停加仓**

### 仓位建议映射

市场温度 → 建议仓位 / 操作建议（由 temperature 命令直接输出）。温度偏冷 + 评分虚高时提醒**分批而非重仓**。

## 数据库表结构备忘

- `kline_indicators`：含 `ktype` = `1d` / `4h` / `1w`；**code 列前缀混乱**，同一标的可能存为 `AAPL` 或 `US.AAPL`，查询建议 `where code=? or code=?` 两种都试
- `score_results`：评分列名是 **`total_score`**（不是 score）；列 = code/date/total_score/signal/breakdown/updated_at
- `market_score`：市场温度；`top_signal_log` / `bottom_signal_log`：信号日志
- 晨星公允价值在 `watchlist.morningstar_fair_value`

## 报告要点

向用户输出时包含：

1. 六步执行状态表（含耗时）
2. 市场温度 + 状态 + 建议仓位 + 与上次的变化
3. STRONG_BUY / BUY 数量分布，**3/3 全通过清单**（dd60<30% + 晨星低估 + 评分≥80）
4. 持仓评分变化，标出 EMA 转多/转空的持仓
5. **跨期对比 STRONG_BUY 榜**：把本期与上两期的榜单并排看，标出「持续在榜 / 掉出 / 新进」。若榜单全是同一类板块（如防御股）但个股频繁换人，说明是「谁跌得多谁得分高」的机械结果，**不是板块看好** —— 报告里要讲清楚这个区别
6. 现货换算 + 加仓档位结论
7. 识别假信号：同一标的连续两日反向 flip（如 9/22 转多→9/23 转空）、或 MFG/MUFG/SMFG 这类外资银行股的反复，直接标注建议忽略
8. 收尾：写入 `F:\TraderAnalysis\.workbuddy\memory\YYYY-MM-DD.md`，并把当日快照追加到
   `F:\TraderAnalysis\.workbuddy\memory\topics\04-signal-pool-log.md` 的「历次快照」表
   （⚠️ 2026-10-19 起 `MEMORY.md` 已拆为索引，不再往它里面写正文）

## 常见坑速查

| 现象 | 原因 | 处理 |
|---|---|---|
| `dirname: command not found` | bash shim PATH 损坏 | 加完整 PATH |
| futu 启动 `expected str, not NoneType` | 缺 APPDATA | export APPDATA |
| update/score 中途被截断 | 前台超时 SIGTERM | 后台运行 + TaskOutput 等待 |
| scp 返回无输出 | 沙箱拦截 .ssh | `dangerouslyDisableSandbox: true` |
| 公网 8000 返回 502 | 云安全组未开放 | 改走 80 端口验证 |
| `no such column: score` | 列名记错 | 用 `total_score` |
| 查 K 线返回 0 行 | code 前缀不符 | 加/去 `US.` 前缀 |
| 停服务后端口仍占用 | 只杀了子进程，npm/uvicorn reloader 父进程成孤儿 | `taskkill //PID <父PID> //T //F` 杀整条链 |
| PowerShell 工具无 stdout | 本机沙箱限制 | 改用 bash + `tasklist` / `taskkill` 验证 |
| `wmic process get commandline` 无输出 | wmic 已废弃 | 用 ctypes 脚本读进程树（见 ⑦） |
| 调富途 skill 脚本报 `无法连接 OpenD: timed out` | OpenD 未启动（11111 无监听） | 启动 `AppData\Roaming\Futu_OpenD\Futu_OpenD.exe`，约 5 秒后可用 |
| 想查 OpenD 安装路径但 `reg.exe` 被拦 | 沙箱程序黑名单禁用 reg.exe | 解析桌面 `Futu OpenD.lnk` 二进制找路径，或直接看已知路径 |
| 晨星估值算出的"折价"大得离谱 | 把 `ms_discount_pct`(上涨空间) 当成折价率读了 | 口径是 `(fv−close)/close`；也可能是 DB 陈旧，跑 ⑧ 核对 |
| 服务器本机 `curl 127.0.0.1/api/...` 404 | nginx default.conf(server_name localhost) 抢占了 80 | 用公网 IP 验证，站点本身正常 |
| K 线出现单日 −50%~−95% 的「暴跌」 | QFQ 前复权 + 增量更新 → 拆股前价格停在旧基准（见 ⑨） | 全量重拉：`scripts/refetch_klines.py <code...>` |
| 重跑 `scan-signals` 后信号数翻倍 | `top/bottom_signal_log` 无唯一约束，重复 INSERT | 先按 `(code, date)` 删除再重算 |
| 库中 K 线最新价 ≠ Futu 实时快照 | 库数据是旧复权基准（未复权断层） | `get_market_snapshot` 对手；以实时快照为准 |
| 拿不到超过 250 根的 K 线 | Futu 不传 `start` 时忽略 `max_count` | 显式传 `start` |
| 最新日的 K 线是**盘中半截** | 守卫上线前（或用了 `--allow-partial`）写入的 | 量比 <1 即半截；正常跑 `update` 已不会产生，见上方「盘中跑已经安全了」 |
| 重跑 `update` 后那根半截 K 线**没变** | 增量更新严格 `date > last_date`，已存在的行永不被覆盖 | 先 delete 该日 1d/1w/4h 再 update（仅历史数据需要） |
| `update` 日志出现「⏭ 已跳过 N 根尚未收盘的 K 线」 | **正常**，守卫在挡盘中那根 | 什么都不用做；要强制写入才加 `--allow-partial` |
| 一批标的连续报 `database is locked` | update 运行期间有别的进程/脚本连了 DB | 等 update 跑完再查；失败的标的重跑一次即可 |
| 报告温度趋势只有两个点 | `temperature` 默认只写最新日 | `temperature --backfill N` 补中间日，**补完要重新 scp** |
| `/api/allocation` 的 `gap` 与实际差很远 | `actual_value` **只统计目标清单内**的代码 | 非目标持仓（LULU/YUMC/TLT 等）要人工补算 |
