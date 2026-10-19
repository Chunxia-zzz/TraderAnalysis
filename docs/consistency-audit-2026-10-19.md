# 一致性核对报告 · 记忆 / 文档 / 代码

> 核对日期：2026-10-19。方法：以**代码为唯一事实源**，逐项反查记忆（`.workbuddy/memory/`）与文档（`docs/`）。
> 结论先行：**三者高度一致**，但发现 **3 处过时信息 + 1 处「计数口径容易误读」**，均不致命，需定向修正。

---

## 一、核对范围与方法

| 维度 | 覆盖 |
|---|---|
| 记忆 | 索引 `MEMORY.md` + 10 个主题文件 `topics/01~10` |
| 文档 | `docs/` 全部 14 个 md（CHANGELOG、api.md、6 份开发文档、3 份设计文档） |
| 代码 | `src/trader_analysis/futu_strategy/` 35 个模块 + 前端 `F:\TraderAnalysisFrontend` |

方法：对记忆/文档中每一个「可证伪的声明」，回到代码用 `grep`/`sqlite`/文件存在性逐一验证，不打折扣。

---

## 二、已对齐项（抽查全绿，可信）

| 记忆/文档声明 | 代码事实 | 判定 |
|---|---|---|
| 评分 6 因子权重 `{weekly_rsi 20, daily_macd_pct 20, boll 15, daily_rsi 20, weekly_macd 10, drawdown 15}` | `scorer.py` `WEIGHTS` 逐字一致 | ✅ |
| 评分无动量项、纯均值回归 | 6 因子方向全同向 | ✅ |
| 市场温度三维 `50/35/15`（日线/周线/价格位置） | `config.MARKET_TEMP_WEIGHTS` = `{0.50,0.35,0.15}` | ✅ |
| 日线用 `rsi6` + 分档 `int(rsi/10)*10` | `market_scorer.py:81-82` | ✅ |
| 仓位映射 30%~120% | `market_scorer.py:278` | ✅ |
| 37 业务端点 + 1 健康检查，8 个写端点 | `api_server.py` 精确 37 `/api` + 1 `/health`，写端点 8 | ✅ |
| 存储 9 张表（`storage.py`） | `storage.py` `_CREATE_TABLES_SQL` 恰 9 张 | ✅ |
| 环境变量 `TA_DB_PATH`、私有 `_get_conn()` | `config.py:151`、`storage.py:224` | ✅ |
| 晨星 `ms_discount_pct = (fv−现价)/现价×100`（上涨空间%） | `api_server.py:146`、`allocation.py:159` | ✅ |
| 观察池 195 只（美股 192 + 港股 3：00700/01211/03690），26 分类 | `watchlist` 表 195 行，HK 恰 3 只，26 分类 | ✅ |
| 温度加成 `composite<40 时最多 +15 分` | `scorer.py:182-184` | ✅ |
| 三份设计文档核对表合计 ✅42/⚠️36/❌12 | 29+23+38=90 项，✅6+11+25=42、⚠️36、❌12 | ✅ |
| 网格 `order_handler.py` 不存在（部分实现） | `grid_trader/` 8 个文件，无 `order_handler` | ✅ |
| `run_backtest -> dict`，`Trade.entry_score` 而非 `total_score` | `backtest.py:519`、`Trade.entry_score` | ✅ |
| 前端 `getTradeSignals`/`getBottomSignals` 死代码 | 在 `trader.js:71/73`，全仓无调用 | ✅ |
| 后端 `query_fundamentals_overview` 死代码 | `storage.py:555`，无调用点 | ✅ |
| `Fundamental.vue` 已删 | `frontend/src/views/` 无此文件 | ✅ |
| K 线 lightweight-charts v4、ECharts 仅温度 | `part_c_api.md` 口径一致 | ✅ |
| 半截 K 线守卫 `market_clock.py` 已存在 | 8442 B，10-17 落盘 | ✅ |
| 认证层已彻底移除（`auth.py`/`auth_storage.py` 不存在） | 文件确实不存在 | ✅ |

---

## 三、发现的问题（3 处过时 + 1 处易误读）

### ⚠️ 问题 1 · 「共 9 张表」实际是 16 张（过时/口径窄）

**记忆与文档**（`topics/09`、`part_b_storage.md`、`CHANGELOG`）都写「共 **9 张表**」。
**代码事实**：`data/indicators.db` 里实际有 **16 张表**：

```
9 张（storage.py）      ：kline_indicators / score_results / market_score / market_score_detail /
                          fundamental_data / position_state / top_signal_log / bottom_signal_log / livermore_signal_log
watchlist               ：watchlist_storage.py（195 行）
content_templates       ：template_store.py（4 行）
grid_config/grid_orders/grid_state：grid_trader/state_manager.py（3 张）
users                   ：cli.py create-admin 会 init（2 行）
（另有 sqlite_sequence 为系统表，不计）
```

**定性**：「9 张表」严格说只是 `storage.py` 单文件建的表数，不是全库表数。这是**表述过窄**，不是数据丢失——但会让读文档的人误以为库只有 9 张表。

**修正方向**：把「9 张表」改为「**storage.py 建 9 张核心表；全库另有 watchlist / content_templates / grid_*×3 / users，共 16 张**」。

---

### ⚠️ 问题 2 · `cli.py create-admin` 断链（代码缺陷，记忆/文档未标记为死代码）

**代码事实**：`cli.py:326-327` 的 `create_admin` 命令 `from ...auth import hash_password` 和 `from ...auth_storage import create_user`，但这两个模块**已被删除**（CHANGELOG 记录「认证系统 v2.8+ 彻底移除」）。

**后果**：`trader-analysis create-admin` 一执行就 `ModuleNotFoundError`。

**记忆/文档现状**：
- `README.md`（futu_strategy_docs）**已如实标注**「cli.py 的 create-admin 因此断链」✅
- 但 `topics/09-docs-and-gaps.md` 的「死代码」清单**只列了 3 个无害函数，没列 `create_admin` 这个会崩的命令**

**定性**：这是**代码自身的遗留缺陷**（不是文档错误），但记忆没把它标为「已知断点」，后续会话可能误用。

**修正方向**：二选一 —— ① 恢复 `auth.py`/`auth_storage.py`（或改为无需认证的 stub）；② 删掉 `create_admin` 命令并同步 CHANGELOG。无论哪种，`topics/09` 都该补一行「create-admin 断链待处理」。

---

### ⚠️ 问题 3 · `backtest.py` 有 `BacktestParams` 类（记忆表述易误读）

**记忆**（`topics/09`）说「`run_backtest() -> BacktestResult` 是错的，**无该类**，返回 `dict`」。
**代码事实**：`backtest.py:519` 确实是 `def run_backtest(params: BacktestParams) -> dict`，返回 `dict` ✅；**但确实存在一个 `BacktestParams` 类**（入参）。

**定性**：记忆说「无 `BacktestResult` 类」**是对的**，但没说清「有 `BacktestParams`（入参）类」，容易让人以为「backtest 模块没有任何 Xxx 类」。这是**表述精度问题**，不是错误。

**修正方向**：`topics/09` 该行改为「`run_backtest(BacktestParams) -> dict`；**无 `BacktestResult`（返回）类**，但**有 `BacktestParams`（入参）类**」。

---

### ⚠️ 问题 4 · 「✅42/⚠️36/❌12」是三份文档合计（易误读为单份）

**记忆**（`topics/09`）写「3 份设计文档文末各有核对表（✅42/⚠️36/❌12）」。
**代码事实**：这是**三份合计**，单份分别是：

| 文档 | ✅ | ⚠️ | ❌ |
|---|---|---|---|
| grid-trading-engine-design.md | 6 | 20 | 3 |
| signal-backtest-engine-design.md | 11 | 9 | 3 |
| position-sizing-strategy.md | 25 | 7 | 6 |
| **合计** | **42** | **36** | **12** |

**定性**：数字本身**准确**，但「各有核对表（✅42…）」的措辞会让人以为**每份**都是 42/36/12。

**修正方向**：`topics/09` 改为「三份设计文档文末各有核对表，**合计** ✅42/⚠️36/❌12（单份见各文档统计行）」。

---

## 四、修正优先级

| # | 问题 | 影响 | 优先级 | 动作 |
|---|---|---|---|---|
| 1 | 「9 张表」vs 16 张 | 新会话可能漏看 watchlist/grid/users 表 | 中 | 改 `topics/09` + `part_b_storage.md` |
| 2 | `create-admin` 断链 | 误跑即崩，且记忆未标记 | **高** | 决定修复 or 删除，并记入 `topics/09` |
| 3 | `BacktestParams` 表述精度 | 低，仅易误读 | 低 | 改 `topics/09` 一行 |
| 4 | 「42/36/12」合计口径 | 低，数字本身对 | 低 | 改 `topics/09` 措辞 |

---

## 五、给后续会话的上下文要点

1. **事实源优先级**：代码 > `docs/` > 记忆。记忆和文档都可能落后于代码，遇到冲突先信代码。
2. **「9 张表」不要当真**：核心 9 张在 `storage.py`，但全库 16 张，grid/watchlist/users 各自独立建表。
3. **`create-admin` 是断的**：别在开发任务里调它；要么修要么删，动手前先看 `topics/09` 是否已处理。
4. **评分/温度/端点/观察池口径全部准确**：这四块是记忆最可靠的部分，可直接引用。
5. **三份设计文档的核对表是「实现现状」的黄金参照**：新会话要判断「某功能做了没」，先翻文档文末核对表，别凭记忆。
6. **记忆结构**：索引 `MEMORY.md` 只给路由，深问必须按路由表读 `topics/NN-*.md`（已实测确认 topics 不会被自动注入）。
