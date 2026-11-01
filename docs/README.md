# 文档索引

> 仓库根目录的 `README.md` / `AGENTS.md` / `CLAUDE.md` / `GEMINI.md` 是**入口层**，不在本目录。
> 这里放**内容层**：搞懂、动手、查字段、改功能、看历史。
> 新增文档请先在本页登记，再决定放在哪一层。

## 我现在要做什么 → 去哪

| 目的 | 去哪 |
|---|---|
| 刚接手，先搞懂这是什么 | [`overview/architecture.md`](overview/architecture.md) |
| 起服务 / 跑日更 | 根目录 [`AGENTS.md`](../AGENTS.md) + `skills/trader-daily-update/SKILL.md` |
| 出问题了（报错、数据不对、部署没生效） | [`guides/troubleshooting.md`](guides/troubleshooting.md) |
| 线上怎么部署、怎么核验 | [`guides/ops/README.md`](guides/ops/README.md) |
| 日报在哪 | [`guides/reports-index.md`](guides/reports-index.md) |
| 查接口 / 字段 / 返回结构 | [`reference/api.md`](reference/api.md) |
| 查数据库表 / 索引 / 约束 | [`reference/storage.md`](reference/storage.md) |
| 改某个功能，得知道它为什么这么设计 | [`modules/`](modules/) 下对应文件 |
| 这个功能到底做了没有 | 两份 engine 文档文末的「实现现状核对表」 |
| 什么时候改的、为什么改 | [`history/CHANGELOG.md`](history/CHANGELOG.md) |
| 看过期的核对结论 | [`history/audits/`](history/audits/)（**不保证仍然正确**） |

## 目录结构

```
docs/
├── README.md                      ← 本文件：唯一导航入口
├── overview/
│   └── architecture.md            三层架构 / 文件树 / 执行流程 / CLI 概览
├── guides/                        动手类
│   ├── troubleshooting.md         18 条「症状 → 原因 → 解法 → 验证」
│   ├── reports-index.md           日报索引（正文含账户信息，不入库）
│   └── ops/                       线上配置副本
│       ├── README.md              抓取命令、部署链路、核验方法
│       ├── trader-api.service
│       ├── nginx-trader.conf
│       └── nginx-gzip.conf
├── reference/                     查询类
│   ├── api.md                     37 端点 + 字段级说明
│   └── storage.md                 15 张业务表、索引、约束
├── modules/                       功能类（设计意图 + 实现现状）
│   ├── data-fetcher.md            Futu 拉数、额度、QFQ 断层、前视偏差
│   ├── indicators.md              指标计算与三套周期配置
│   ├── scoring.md                 6 因子、信号等级、连续映射
│   ├── market-temperature.md      三维温度、口径反转、仓位映射
│   ├── watchlist.md               标的池模型与 CRUD
│   ├── fundamental.md             基本面 5 因子
│   ├── trade-executor.md          交易执行与调度
│   ├── grid-engine.md             网格引擎（文末有实现核对表）
│   └── backtest-engine.md         回测引擎（文末有实现核对表）
├── history/                       记录类
│   ├── CHANGELOG.md               倒序变更史
│   └── audits/                    一次性核对快照，**不作为现行结论**
└── archive/                       已过时，仅留证据（目前为空）
```

## 维护规则

1. **位置由「读者目的」决定**，不由「开发顺序」决定。旧命名 `part_a_*` / `part_b_*` 是施工顺序，已废弃。
2. **新增文档先在本页登记**，否则等于没写——没人能找到不存在于索引里的文件。
3. **过时内容不删历史**：结论被推翻的，移入 `history/audits/` 并在顶部标注失效；
   对象已不存在的（文件/命令已删），正文直接删除。
4. **一次性过程物不进 modules**：审计报告、迁移方案、验收清单完成即归 `history/audits/`。
5. **重复内容合并而非并存**：同一件事只允许一份文档维护，另一处只留指针。
6. **仓位意图不入文档**：目标权重、标定区间、分批比例、加仓闸门属随时可变的个人想法，
   只看 `data/target_allocation.json` 与 `GET /api/allocation`（见 `AGENTS.md` §5 第 9 条）。

## 2026-11-01 重组说明

本次把文档从「按开发阶段平铺」（`docs/` 根下 20 个文件 + `futu_strategy_docs/` 双层同名目录）
重组为按用途分层。**早期文档里的相对链接可能失效**，以本页路径为准。

同批完成的内容精简（合计约 880 行）：

- `modules/api-server.md` **合并进 `reference/api.md` 后删除**（端点分组统计与历史沿革并入附录）
- `modules/market-temperature.md`：删除未实现的 §4.3(VIX) / §4.5(量能) / §4.6(避险) 正文，
  以及 §8 与 `modules/indicators.md` 重复的示例代码（1721 → 1241 行）
- `modules/watchlist.md`：`§8 兼容性与迁移策略`、`§12 验收标准` 标记作废（迁移已完成、JSON 已删）
- `history/audits/` 的核对报告加「结论已过时」声明
