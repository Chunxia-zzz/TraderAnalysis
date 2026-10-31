# 日报索引

> 日报**正文不入库**：含富途账户 ID、总资产与现金金额，违反「凭证与资产规模不进公开仓库」的红线。
> 本文件只做**索引与位置登记**，让任何 agent / 任何机器都知道这些报告存在、在哪、怎么取。

## 权威副本

| 项 | 位置 |
|---|---|
| 资料库空间 | `amo3KT37smg61B4NxXioH5`（WorkBuddy 资料库） |
| 本地副本 | `logs/reports/YYYY-MM-DD-daily-report.md`（`logs/` 已 gitignore，仅本机留存） |
| 台账 | 同空间内的记录表，每条日报一行（日期 / 市场温度 / 建议仓位 / 强买数 / 买入数 / 3-3 通过 / 结构 / 关键动作 / 日报链接） |

## 已归档

| 数据日 | 报告 | 本地副本 | 云端 | 备注 |
|---|---|---|---|---|
| 2026-10-30 | 日更日报 | `logs/reports/2026-10-30-daily-report.md` | <https://www.workbuddy.cn/space/d/b82ZYvc4dSNys49zqco7nA> | 台账 record `6XO08f9D4IvkL3iQrt2TXM` |

> 更早的日报散落在资料库中，尚未逐条回填本表；补录时按上表格式追加。

## `logs/` 目录约定（2026-11-01 起）

```
logs/
├── reports/          # 报告类：日更日报、晨星核对明细（morningstar_audit.json）
├── scratch/          # 一次性排查物：图表截图、临时 json、诊断文本（可随时清空）
├── serve/            # 进程输出：api_server.log / be_*.log / fe_*.log / local_cron.log
├── score_log.jsonl   # 代码写入（config.SCORE_LOG_FILE）
└── trade_log.jsonl   # 代码写入（config.TRADE_LOG_FILE）
```

- 根目录**只保留代码固定写入的两个 jsonl**；新增文件按用途进子目录，不要堆在根上
- `logs/` 整体被 gitignore，上述结构只在本机生效
- 日报正文若确需入库，**必须先脱敏**：账户 ID → 「模拟账户」，绝对金额 → 删除或改比例

## 新增一份日报

1. 正文写到 `logs/reports/YYYY-MM-DD-daily-report.md`（数据日，不是执行日）
2. 同步到资料库空间（正文全量覆盖，URL 保持不变）
3. 台账追加一行
4. 在本文件「已归档」表追加一行（日期 / 本地路径 / 云端链接 / 台账 record）

## 晨星核对明细

`scripts/audit_morningstar.py` 的差异输出写到 `logs/reports/morningstar_audit.json`（脚本路径已同步）。
只记录与 Morningstar API 差异 >1% 的标的，字段：`code` / `db_fv` / `api_fv` / `diff_pct` / `close`。
