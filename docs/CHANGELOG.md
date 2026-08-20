# Changelog

本文件记录项目的重大版本变更。格式参考 [Keep a Changelog](https://keepachangelog.com/)。

---

## [2026-08-20]

### 新功能 — 自媒体内容生成

- **自媒体文案生成器**（`content_generator.py` + `GET /api/content-generator`）：基于交易信号（道氏趋势 + 估值）生成小红书/知乎/公众号三套发布文案，纯模板渲染零成本
- **市场复盘报告**（`review_generator.py` + `GET /api/review`）：日复盘/周复盘，固定覆盖大盘（标普/纳指/黄金/比特币）+ 七姐妹 + 交易机会（放最后）
- **内容模板可编辑**（`template_store.py` + `content_templates` 表）：文案与复盘模板从代码抽离到 DB，`{占位符}` 渲染，支持页面在线编辑 + 恢复默认（`GET/PUT/DELETE /api/content-templates`）
- **标的中文名映射**（`stock_names.py`）：196 只标的 ticker→中文名（如 AVGO→博通），文案优先用中文名

### 后端增强

- **评分/信号自动补算**：`score` 和 `scan-signals` 自动检测「上次结果日期 vs K 线最新日期」，补算中间缺失的交易日的评分/信号（几天没跑也不留缺口）
- **新增 5 个交易信号**：底部 RSI上穿50中轴 / 布林收口放量突破 / 向上跳空缺口；顶部 向下跳空缺口 / 突破52周新高
- **增量更新优化**：`update` 只拉最近 30 根而非全量 250 根，节省富途行情额度
- **清理**：market_scorer 移除未使用的 gld/vix 参数；detect_all 静默异常改为记日志；daily-picks 阈值统一为 `config.DAILY_PICKS_MIN_SCORE`

### Bug 修复

- RSI 除零：纯上涨时 RSI 返回 NaN → 修复为 100
- `runner` 评分缺 `market_composite` → 与 `score` 命令结果一致
- `sell_advisor` SELL_3 阶段不可达 → 状态机精简为 HOLD→SELL_1→SELL_2→EMPTY
- `detect_ma5_no_recovery` 空序列 `all()` 恒 True → 修复误报
- `_score_drawdown` high 全 NaN 边界 → 修复
- `scan-signals` 信号日期用 `date.today()` → 改为 K 线最新日期（修复美股时差下日期错位一天）

### 前端

- **市场复盘页**（`Review.vue`）：日/周复盘切换、大盘/七姐妹结构化卡片、交易机会可展开生成荐股文案、模板编辑弹窗
- 文案生成合并进市场复盘页，删除独立文案生成页

### 标的池

- 剔除 7 只杠杆/重复 ETF（YINN/SOXL/KORU/HK.07709/GDXU/EUV/FOTO），203 → 196 只
- 标的池加入规则写入 `part_e_watchlist_management.md`（纳入标准 + 排除项）

---

## [Unreleased] — 2026-07-31

### 后端

- **道氏理论三层趋势分析**（`analyze_dow_trend`）：潮汐（周线 MA20/60）+ 波浪（日线 MA20/60）+ 涟漪（RSI + BB位置）
  - 整合估值维度，输出 8 种核心策略场景（顺势做多/回调加仓/等回踩做多/空仓等待/反弹做空 等）
  - 周线 MA 无数据时自动 on-the-fly 计算（fallback）
- **基本面估值 API**（`GET /api/fundamental`）：分析师目标价 + 晨星公允价值 + 折价率，支持日期筛选
- **高置信度低估做多 API**（`GET /api/daily-picks`）：巴菲特原则筛选——晨星低估 + 周线涨潮 + 日线回调 + 评分≥70
  - 自动取最近完整评分日（HAVING COUNT >= 10），避免部分评分日遗漏
- **形态信号置信度评分**（`_score_pattern_confidence`）：根据道氏趋势给每个技术形态标注置信度（高/中/低）
- **量能上下文解读**：成交量比结合趋势阶段（涨潮回调缩量=健康 / 退潮反弹放量=短期底）
- **关键位置增强**：MA60 标记为关键位 + 道氏上下文描述 + 做多做空盈亏比计算
- **标的管理 API 增强**（`GET /api/watchlist`）：批量查询最新收盘价 + 晨星折价率，ETF 不展示折价
- **K 线图表支持 4H**（`GET /api/indicators`）：4H 日期自动转 Unix 时间戳，正则扩展为 `^(1d|4h|1w)$`
- **基本面估值日期联动**：`/api/fundamental` 支持 `?date=` 参数
- **技术分析日期联动**：`/api/analysis` 支持 `?date=` 参数，切片到指定日期
- 修复 `analyze_dow_trend` 中 valuation 变量提前引用导致的 UnboundLocalError

### 前端

- **个股技��分析页（Dashboard）全面重构**：
  - 删除"最新技术指标""均线&布林带""MACD&RSI"三个券商可获得的数据卡片
  - 新增 **基本面估值** 卡片（分析师目标价 + 晨星公允价值 + 折价率）
  - 新增 **道氏技术面** 卡片：三层趋势 + 综合策略 + 关键位置 + 盈亏比 + 形态信号（带置信度点）+ 量能信号
  - 删除 BB位置(%B)（券商可见），替换为量能上下文解读
  - 综合评分移到页面底部作为结论
  - 所有卡片支持日期联动 + 标的切换
- **交易信号页新增"低估做多"tab**：高置信度低估做多机会，显示晨星折价 + RSI + 策略信号
- **标的管理页**：新增晨星折价列 + 排序功能（默认折价高→低），隐藏空数据列（Forward PE、推荐策略）
- **个股图表支持 4H K 线**：时间段新增 4H 选项 + 日期显示 YYYY-MM-DD 格式 + 悬停十字光标格式修复
- 修复 `<a-spin>` 多根元素 `patchKeyedChildren` 错误 + `<a-empty :image="null">` Antd 兼容问题

## [Unreleased] — 2026-07-30

### 前端

- **"交易信号"页面重构（原"个股主升趋势"）**：导航名更新，整合转势+动量+超卖三合一
  - 拆分"牛熊转换"为独立 **空转多 / 多转空** 两个 tab，各含 4H/日线周期切换
  - 新增 **主跌浪超卖** tab：显示 6 因子评分 ≥ 60 的超卖标的，按评分降序
  - 移除 **多头飘带** 区块（冗余）
  - 移除 **牛熊转换5根回看** 模糊逻辑，统一使用 EMA 交叉精确检测
- **下架 `/scores-overview` 路由**：功能已合并到交易信号页面，导航栏合并为"交易信号"
- **修复** `<a-spin>` 多根元素导致的 `patchKeyedChildren` Vue 运行时错误
- **修复** `<a-empty :image="null">` 导致的 `Cannot use 'in' operator` Ant Design Vue 错误

## [Unreleased] — 2026-07-21

### 后端

- **标的池扩充至 203 只**：新增标普/纳斯达克 $50B+ 市值龙头股（金融/医疗/消费/工业/能源/国际），11 只 S&P 行业 ETF，商品对冲 ETF
- **4H K 线支持**：新增 `FOUR_HOUR_INDICATOR_CONFIG`，`daily_update.py` 增量更新支持 4H（KLType.K_240M），ktype="4h" 存入 `kline_indicators` 表
- **EMA 交叉信号引擎**（`ema_cross_detector.py`）：检测 EMA5/EMA30 金叉死叉，支持日线+4H 双维度
  - 信号类型：`EMA_CROSS_BULL_1D` / `EMA_CROSS_BULL_4H`（空转多）、`EMA_CROSS_BEAR_1D` / `EMA_CROSS_BEAR_4H`（多转空）
  - 集成到 `scan-signals` 命令（含 `--backfill` 回溯）
- **新增 `GET /api/ema-cross-signals` 端点**：按日期查询 EMA 交叉信号，支持 `?date=YYYY-MM-DD`
- **基本面目标价批量拉取脚本**（`scripts/fetch_fundamental_targets.py`）：拉取分析师平均目标价 + 晨星公允价值，写入 watchlist 表
- **`/api/scores/overview` 性能优化**：从逐标的查询改为批量查询，响应时间 4s → 0.2s
- **新增一次性脚本** `scripts/backfill_klines.py`：补全新标的日线/周线/4H 数据

### 前端

- **"个股主升趋势"页面新增 EMA 交叉信号 section**：4H/日线 tab 切换，显示空转多/多转空信号
- **日期筛选改为按钮触发**：选择日期后点"查询"按钮执行，EMA 信号跟随日期联动
- **标的池管理页面分页**：默认 20 条/页，可切换 50/100

---

## [v0.9] — 2026-07-10

### 后端

- **底部信号系统重写**（`bottom_detector.py`）：按技术方案实现 7 个底部信号
  - NEAR_SUPPORT（均线支撑）、DEEP_V（深V确认）、VOLUME_SHRINK（缩量企稳）、RSI_BOTTOM_DIV（RSI底背离）、W_BOTTOM（W底形态）、SUPPORT_CONFIRM（支撑确认）、RECLAIM_MA5（站上MA5）
  - DEEP_V 不依赖距离门槛，适配高波动动量资产（low < MA < close 即可）
- **新增 `BOTTOM_DETECTION_CONFIG`**（`config.py`）：7 个信号的独立配置参数
- **新增 `bottom_signal_log` 表**（`storage.py`）：底部信号持久化存储 + 查询函数
- **新增 `scan-signals` CLI 命令**（`cli.py`）：支持 `--backfill N` 回溯历史顶部+底部信号
- **`/api/trade-signals` 支持 date 参数**：传入日期查历史已存信号，不传则实时计算
- **新增 `/api/bottom-signals` 端点**：底部信号历史查询（镜像 `/api/top-signals`）
- **`runner.py` 集成底部信号检测**：每日循环中自动检测并存储底部信号
- **`serve` 命令启用热重载**：`reload=True`，开发时改代码自动生效
- **"持续调整"标签调整**：MA5_NO_RECOVERY 从"建议清仓"改为"观望"

### 前端

- **交易信号按日期筛选**（`Dashboard.vue`）：切换日期时信号面板同步更新
- **底部信号从 4 个升级到 7 个**：适配后端新信号系统
- **信号加载合并到 loadData**：移除独立 loadSignals，信号与评分/分析统一加载
- **新增 `getBottomSignals` API 函数**（`trader.js`）

---

## [Previous] — 2026-07-05

### 前端

- **首页全面重设计**（`Home.vue`）：参考优质前端视觉效果，用纯 CSS + IntersectionObserver 重写，零新依赖
  - 6 个全屏全宽 Section（Hero / 核心能力 / 市场温度展示 / 评分雷达 / 工作流 / CTA），通过 `width: 100vw; left: calc(-50vw + 50%)` 突破父容器 `max-width: 1400px` 限制
  - 双主题（暗色/亮色）独立 CSS 变量体系，切换状态持久化到 `localStorage`，不影响全局主题
  - 滚动动画：`IntersectionObserver` 驱动的 fade+slide 入场效果、SVG 仪表盘弧线填充、雷达多边形描边、时间线渐进显示
  - 数字滚动特效：缓动函数驱动的计数动画（`easeOutCubic`）

- **Dashboard 个股技术分析集成**（`Dashboard.vue`）：新增支撑/压力位和形态趋势两张卡片
  - **支撑 & 压力位** 卡：支撑（绿色）/ 压力（红色）分组，显示价格、标签、与当前价的百分比距离、强度点（●●○ 样式）
  - **技术形态 & 趋势** 卡：命中形态以 Tag 展示（多头绿/空头红，悬停显示详细描述）；趋势数据含主趋势、短期趋势、RSI12、MACD偏向、%B、成交量比、ATR14 及 ATR 波动率
  - 修复 MACD & RSI 卡中 `rsi14` → `rsi12` 字段名

- **API 模块扩展**（`trader.js`）：新增 `getAnalysis(code, ktype)` 函数，调用 `/api/analysis` 端点

- **个股主升趋势页增强**（`MomentumLeaders.vue`）：
  - 新增「多头飘带」Section：EMA5 > EMA30 的全部标的，按动量评分降序
  - 新增「牛熊转换」Section：近5日内 EMA5/EMA30 发生金叉（空转多）或死叉（多转空）的标的，分别标注 ↑/↓
  - 工具栏统计同步显示三类数量

- **EMA 飘带判断逻辑优化**（`api_server.py`）：
  - 旧逻辑：6条EMA全部严格排列才算 green/red，否则 mixed
  - 新逻辑：`ema5 > ema30` → green，否则 red，去掉 mixed 分类
  - 多头飘带标的从 7 只增加到 22 只（覆盖过渡期标的）

- **飘带翻转检测**（`api_server.py`）：`/api/scores/overview` 每条记录新增 `ribbon_flip` 字段：`"to_bull"`（空转多）/ `"to_bear"`（多转空）/ `null`（无翻转），检测窗口为近5个交易日

- **页面与分组重命名**：
  - 导航：机会速览 → 个股超买超卖；主升浪龙头 → 个股主升趋势
  - 分组 Tab：可执行 → 严重超卖且站上MA5；强烈买入 → 严重超卖；建议买入 → 超卖；观望 → 中性
  - Section 标题同步更新

### 新增

- **技术分析辅助决策模块**（`futu_strategy/technical_analysis.py`，新建）：纯计算层，基于本地 DB 数据提供三类分析：
  - `find_support_resistance(df)`：Swing Pivot 检测（左右各 n 根确认），ATR×0.6 距离聚类合并，近期命中点权重×2；叠加 MA20/MA60/MA250 动态均线位，过滤 ±25% 以外的无效位，各返回最多 5 个支撑/压力位（含价格、强度、标签、类型）
  - `detect_patterns(df)`：检测 17 类技术信号，包括均线多/空头排列、MA5/MA20 金死叉、MA20/MA60 金死叉、EMA 飘带多/空、MACD 金区/死区/金叉/死叉、RSI 超买超卖、布林带突破、放量异动；仅返回命中信号
  - `analyze_trend(df)`：返回主趋势（up/down/sideways）、短期趋势、RSI12、MACD 偏向、%B 布林带位置、成交量比、ATR14 及 ATR 波动率百分比

- **新 API 端点**（`api_server.py`）：`GET /api/analysis?code=US.MU&ktype=1d`，聚合以上三个函数输出，返回格式：
  ```json
  {
    "code": "US.MU", "ktype": "1d", "date": "...", "close": 975.56,
    "supports": [...], "resistances": [...],
    "patterns": [{"id", "label", "bullish", "desc"}, ...],
    "trend": {"primary", "short_term", "rsi12", "macd_bias", "bb_pct_b", "vol_ratio", "atr14", "atr_pct"}
  }
  ```
  无需 OpenD，纯读本地 SQLite

---

## [v3.5.0] — 2026-06-18

### 新增

- **黄金 / 比特币温度评分**（`market_scorer.py`）：新增 `compute_asset_temperature(asset_key)` 函数，对 GLD（黄金）和 BTC（IBIT 代理）独立计算三维度温度评分（日线技术面 50% + 周线技术面 35% + 价格位置 15%），阈值按资产波动特性独立校准（GLD 回撤零分线 25%/MA200 ±20%；BTC 50%/±60%）
- **资产历史温度评分**（`market_scorer.py`）：新增 `compute_asset_temperature_history(asset_key, days)` 函数，对最近 N 个交易日逐日滑窗计算，返回评分序列
- **新 API 端点**（`api_server.py`）：`GET /api/asset-temperature/history?asset=GLD&days=60`，返回单资产历史温度序列
- **市场温度 API 扩展**（`api_server.py`）：`/api/market-temperature` 响应新增 `gld_temp` / `btc_temp` 字段，实时附加黄金和比特币温度
- **新增标的 SOXX / SOXL**（`watchlist.json`）：iShares 半导体 ETF + Direxion 半导体三倍 ETF，分类 `semiconductor`，已拉取近一年 K 线并计算写入评分

### 前端

- **MarketTemperature.vue 三 Tab 视图**：顶部新增视图切换（美股大盘 / 黄金 / 比特币），黄金和比特币各有独立 Hero 卡片（综合评分 + 三维度进度条）、六指标网格（价格/日RSI/周RSI/MA200偏离/ATH回撤/52周位置）以及 60 天历史趋势折线图；Tab 颜色：黄金 `#946800`，比特币 `#f7931a`
- **市场大盘快捷跳转**：Hero 卡片底部新增 SPY K线 / QQQ K线 链接，与 CNN 指数链接并排
- **主升浪龙头导航修复**（`MomentumLeaders.vue`）：点击标的由跳转评分页改为跳转 K 线图页（与机会速览行为一致）
- **图表切换 ECharts 复用修复**（`MarketTemperature.vue`）：视图切换时先 dispose 旧实例再重建，解决切回大盘视图历史趋势消失的问题

### 图表增强（`IndicatorChart.vue`）

- **指标数值悬浮层**：仿富途风格，每个子图（价格/成交量/MACD/RSI）顶部显示当前鼠标悬停 bar 的数值；不悬停时显示最新一根数据，使用 DM Mono 等宽字体
- **EMA 多空带实体填充**：使用 Lightweight Charts `ISeriesPrimitive` 接口直接在 canvas 绘制 EMA5~EMA30 之间的色带，多头（EMA5 > EMA30）蓝色半透明，空头（EMA5 < EMA30）红色半透明，交叉点线性插值处理
- **RSI 字段修复**：`rsi14` 改为 `rsi6`（数据库实际存储字段名）

---

## [v3.4.0] — 2026-05-28

### 新增
- **EMA 飘带回测策略**（`backtest.py`）：新增 `ribbon_long`（空转多买入/多转空卖出）和 `ribbon_short`（多转空做空/空转多平空）两种模式，不依赖评分系统，由 ema5/ema30 翻转驱动
- **EMA 飘带状态字段**（`api_server.py`）：`/api/scores/overview` 响应新增 `ema_ribbon` 字段（`green`/`red`/`mixed`），标识各标的当前 EMA 多空排列状态
- **机会速览 EMA 飘带徽标**（`ScoresOverview.vue`）：每张股票卡片显示飘带状态（多头带/空头带/纠缠中），空头带卡片有警示背景
- **K 线图飘带翻转标记**（`IndicatorChart.vue`）：开启 EMA 多空带后，在翻转日显示绿色向上三角（空转多）和红色向下三角（多转空），悬停显示日期
- **新增标的 US.KORU**：加入标的池（半导体分类），拉取近一年日线（270根）+ 周线（52根）数据
- **Chart.vue 默认指标**：从机会速览跳转时自动读取 URL `code` 参数；默认开启 EMA 多空带，关闭 MA5/MA10/BOLL
- **机会速览点击跳转**：由个股技术分析页改为跳转至 K 线图页面（`/chart?code=...`）

### 变更
- **移除认证系统**（`api_server.py`）：删除 `/api/auth/*` 和 `/api/users/*` 所有端点及 `get_current_user`/`require_admin` 依赖，全端点无需鉴权
- **前端认证清理**（`trader.js`、`router/index.js`、`App.vue`）：移除 Bearer token 拦截器、401 跳转、路由守卫、登录/用户管理路由及导航入口
- **storage.py**：新增 `query_ema_ribbon_data()` 函数，供飘带回测模式读取 ema5/ema30 历史数据

### 修复
- 修复 `App.vue` 重构后 `computed`/`useRoute` 未 import 导致的启动报错

---

## [v3.3.0] — 2026-05-23

### 前端：机会速览拆分为两个独立页面

**背景：** 原 ScoresOverview 页同时展示价值评分和主升浪龙头，两类逻辑定位不同，混在一起不便于快速判断。

**新增页面 `MomentumLeaders.vue`（路由 `/momentum-leaders`）：**

- 专门展示动量评分 ≥ 70 的主升浪龙头标的
- 展示：动量评分（大字红色）、价值评分、MA5状态（上/下）
- 复用 `getScoresOverview()` API，从 `momentum_leaders` 字段取数，从 `actionable` 匹配 `above_ma5`
- 点击卡片跳转个股技术分析页

**修改 `ScoresOverview.vue`（路由 `/scores-overview`）：**

- 移除「主升浪龙头」分区和头部汇总中的「主升浪 X 只」标签
- 保留全部价值评分分区：可执行机会、强烈买入、建议买入、观望

**导航栏（`App.vue`）：**

- 「机会速览（价值）」右侧新增「主升浪龙头」导航链接

---

## [v3.2.0] — 2026-05-12

### 新增：止盈止损自动计算 (TP/SL)

**新模块 `tp_sl.py`：**

- 基于 ATR（波动率）+ 支撑/阻力位（技术面）的混合算法
- 止损 = max(ATR止损, 支撑位止损) — 取较紧者
- 止盈 = min(阻力位, R:R目标) — 取较保守者
- 输出：止损/止盈价、方法来源、盈亏比、仓位建议

**新 API 端点 `GET /api/tp-sl?code=US.NVDA`：**

- 参数：`atr_multiplier`(默认2.0)、`min_rr_ratio`(默认2.0)
- 返回完整风险评估 JSON（支撑位、阻力位、R:R、仓位建议）

**新指标 ATR14：**

- `indicators.py` 新增 `_atr()` 函数（Wilder smoothing）
- `config.py` 日线配置新增 `"atr": [14]`
- `storage.py` 新增 `atr14` 列
- 已全量回填 41 只标的历史 ATR 数据

### 新增：多空飘带指标 (MA Ribbon)

**后端：**

- `config.py`：日线/周线配置新增 `"ema": [5, 10, 15, 20, 25, 30]`
- `indicators.py`：EMA 计算逻辑已有，现通过配置激活
- `storage.py`：`kline_indicators` 表新增 `ema5`~`ema30` 六列
- `/api/indicators` 响应新增 `ema5`~`ema30` 字段，前端可直接使用

**用途：**

多空飘带是一组 EMA 形成的带状区域，用颜色区分多空趋势：
- 短 EMA（ema5）> 长 EMA（ema30）→ 红色飘带（多头）
- 短 EMA（ema5）< 长 EMA（ema30）→ 绿色飘带（空头）
- 飘带宽度反映趋势强度，收窄为方向选择信号

### 修复

- `runner.py`：修复评分后日志 `KeyError: 'triggered'`（v4 评分 breakdown 不再含 triggered 字段，改为展示得分最高的前 3 因子）

---

## [v3.1.0] — 2026-05-11

### 新增：趋势跟踪策略 + 动量评分 + 买入确认

**回测引擎新增两种策略模式：**

- `trend`：趋势跟踪模式——评分达标买入，收盘跌破 MA（ma5/ma10/ma20）时卖出。适合强势股吃主升浪
- `entry_confirm=above_ma5`：买入确认——评分达标后不立即买，等收盘站上 MA5（确认止跌反转）再买入

**机会速览接口增强（`GET /api/scores/overview`）：**

- 每个标的新增 `above_ma5`(bool)、`close`、`ma5`、`momentum_score`(0-100) 字段
- 新增 `actionable` 分组：评分高 + 站上MA5 = 确认反转可执行
- 新增 `momentum_leaders` 分组：动量分≥70 = 主升浪龙头

**动量评分 5 维度（满分100）：**

| 维度 | 分值 | 逻辑 |
|------|------|------|
| 均线多头排列 | 25 | MA5>MA10>MA20>MA60 |
| RSI强势区 | 20 | RSI 50-90 线性给分 |
| MACD方向 | 20 | DIF>0 且 DIF>DEA |
| 20日涨幅 | 20 | 0-30% 线性映射 |
| 量能配合 | 15 | 量比≥1.5 满分 |

---

## [v3.0.0] — 2026-05-10

### 新增：日内网格交易引擎 (P0)

基于 Futu OpenD 实时行情推送的自动网格交易引擎，支持模拟盘/实盘切换。

**新模块 `grid_trader/`：**

- `engine.py`: 主引擎（行情订阅 → 网格决策 → 自动下单 → 状态持久化）
- `strategy.py`: 网格线计算 + 穿越检测 + 状态决策
- `executor.py`: 富途下单封装（限价单）
- `risk_control.py`: 仓位/亏损/次数/时段 四重风控
- `state_manager.py`: 3 张新表（grid_config/grid_orders/grid_state）
- `quote_handler.py`: 实时报价回调

**新 CLI 命令：**

- `trader-analysis grid-create`: 创建网格配置
- `trader-analysis grid-start <id>`: 启动引擎（长驻进程）
- `trader-analysis grid-stop <id>`: 停止引擎
- `trader-analysis grid-status [id]`: 查看状态

**新 API 端点：**

- `GET /api/grid/status?config_id=1`: 网格运行状态
- `GET /api/grid/orders?config_id=1`: 交易记录

---

## [v2.9.0] — 2026-05-10

### 新增：信号回测引擎 + 个股评分 v4

**信号回测引擎：**

- 新模块 `backtest.py`：验证"评分达标时买入，持有N天后卖出"的历史收益
- CLI: `trader-analysis backtest US.SNDK --threshold 40 --holding-days 10`
- API: `GET /api/backtest/run?code=US.SNDK&threshold=40&holding_days=10`
- 支持冷却期去重（none/holding/custom）
- 输出：胜率、平均收益、Sharpe-like、Profit Factor 等完整统计

**个股评分 v4 重构：**

- RSI 映射放宽：(70-RSI)/50 → (80-RSI)/60，更早识别回调
- 新增 C6 回撤因子（替代 MA250偏离）：60日回撤 5%~25% 线性给分，强势股回调也能触发
- 新增大盘温度加成：market composite < 40 时最多 +15 分
- 信号阈值降低：BUY 70→60，STRONG_BUY 90→80
- 回测验证：2025-04关税冲击时 NVDA/META/AMD 从 NO_ACTION 升级为 BUY

**Bug 修复：**

- `daily_update.py`: 修复 `timeframe` 参数缺失 + `timestamp`/`date` 列名映射
- `storage.py`: 修复 `batch_upsert` 中 col_map 导致 date NULL 的问题
- `providers.py`: 移除 `max_count` 参数（Futu QFQ 模式下行为异常）
- 增量更新增加 1s 间隔避免 Futu API 限频

---

## [v2.8.0] — 2026-05-10

### 变更：市场温度仓位映射重构（Breaking Change）

仓位范围从 [10%, 90%] 扩展为 [30%, 120%]，极端层从单级改为两级。

**仓位映射三层结构：**

- 正常区（composite > 25）：`target = 85 - (composite - 25) × (55/75)`，范围 30%~85%
- 轻度极端（composite ≤ 25）：`target = 85 + (25 - composite) × (15/10)`，范围 85%~100%
- 重度极端（composite ≤ 15 AND SPY日RSI<30 AND SPY周RSI<30）：`target = 100 + (15 - composite) × (20/15)`，范围 100%~120%

**变更理由：**

- 美股长牛前提下，最低 30% 底仓保证不踏空（原 10% 过于保守）
- 两级极端层让加仓节奏更平滑（轻度极端 14天触发 vs 旧方案仅1天）
- 重度极端 RSI 门槛从 <25 放宽至 <30，避免极端恐慌时因条件过严错失加仓窗口

**回测验证（900天 2022-09~2026-05）：**

- 均值仓位从 39.3% 提升至 56.9%
- 2025-04 关税冲击（SPY -14%）：仓位 48%→79%，节奏合理
- 2025-11 回调（SPY -4.5%）：仓位 54%→85%
- 2026-03 大跌（SPY -15%+）：轻度极端 13天 + 重度极端 1天，最高 104%

---

## [v2.7.0] — 2026-05-07

### 新增：基本面分析模块（yfinance + 5因子评分）

为系统新增基本面评估能力，与现有技术面评分互补。数据源为 yfinance，不依赖 Futu OpenD。

**新 API 端点：**

- **`GET /api/fundamental/latest?code=US.NVDA`**：单标的基本面数据 + 评分（分组结构化响应）
- **`GET /api/fundamental/overview`**：全标的基本面速览（UNDERVALUED / FAIR / OVERVALUED 分组）

**新 CLI 命令：**

- **`trader-analysis fundamental`**：批量拉取基本面数据并评分（`--codes` 可选）
  - 自动同步 forward_pe/eps/roe 等到 watchlist 表
  - 自动刷新快照字段（trailing_pe, market_cap 等）

**5 因子评分体系（满分 100）：**

| 因子 | 权重 | 逻辑 |
|------|------|------|
| 估值折价 | 30 | 目标价上行空间 |
| PE 合理性 | 20 | Forward PE 越低越好 |
| 成长性 | 20 | 营收+盈利双增长 |
| 财务健康 | 15 | ROE+利润率+低负债 |
| 分析师共识 | 15 | 推荐等级×覆盖人数 |

**架构变更：**

- 新增 `fundamental_fetcher.py`：yfinance 批量采集 + code 映射 + 限频重试
- 新增 `fundamental_scorer.py`：5 因子连续映射评分引擎
- `storage.py`：新增 `fundamental_data` 表 + upsert/query 函数
- 新增依赖：`yfinance>=0.2.36`

**技术方案**：`docs/futu_strategy_docs/futu_strategy_docs/part_f_fundamental.md`

---

## [v2.6.0] — 2026-05-07

### 新增：标的池管理模块（SQLite CRUD + 富途选股）

将标的池从静态 `data/watchlist.json` 迁移到 SQLite，支持动态 CRUD 管理和富途选股填充。

**新 API 端点：**

- **`GET /api/watchlist`**：改为从 DB 读取，支持 `?category=&status=&market=&search=` 筛选
- **`GET /api/watchlist/{code}`**：查询单只标的详情
- **`POST /api/watchlist`**：新增标的（admin），自动从富途填充基础信息
- **`PATCH /api/watchlist/{code}`**：修改可编辑字段（admin），只读字段返回 400
- **`DELETE /api/watchlist/{code}`**：删除标的（admin），不删历史数据
- **`POST /api/watchlist/batch`**：批量新增（admin）
- **`POST /api/watchlist/refresh-snapshot`**：刷新静态快照字段（admin，需 OpenD）
- **`GET /api/stock-filter/search`**：条件选股（需 OpenD）
- **`GET /api/stock-filter/info`**：单股信息查询

**新 CLI 命令：**

- **`trader-analysis migrate-watchlist`**：从 JSON 一次性迁移到 SQLite（`--dry` 预览）
- **`trader-analysis refresh-snapshot`**：刷新快照字段（`--codes` 可选）

**架构变更：**

- 新增 `watchlist_storage.py`：watchlist 表 DDL + 完整 CRUD
- 新增 `stock_info_fetcher.py`：富途 `get_stock_basicinfo` / `get_market_snapshot` / `get_stock_filter` 封装
- `config.py`：`WATCHLIST` 改为动态代理，从 DB 读取（表为空时回退 JSON）
- 字段分层：静态（自动填充，不可改）vs 动态（用户手动维护）

**技术方案**：`docs/futu_strategy_docs/futu_strategy_docs/part_e_watchlist_management.md`

---

## [v2.5.0] — 2026-05-06

### 新增：JWT 认证体系（P0）

为上云部署添加最小化认证层，阻止未授权公网访问。

**新功能：**

- **`POST /api/auth/login`**：用户登录，返回 JWT access_token（7 天有效期）
- **`GET /api/auth/me`**：获取当前登录用户信息
- **`POST /api/auth/change-password`**：修改当前用户密码
- **`trader-analysis create-admin` CLI 命令**：首次部署创建管理员账号
- **所有 `/api/*` 端点**：需要携带 `Authorization: Bearer <token>` 才能访问
- **公开端点白名单**：`/health`、`/api/auth/login`、`/docs`、`/openapi.json`

**架构变更：**

- 新增 `auth.py`：JWT 签发/验证、密码哈希（bcrypt）、FastAPI 认证依赖
- 新增 `auth_storage.py`：users 表（SQLite）CRUD 操作
- CORS `allow_methods` 从 `["GET"]` 改为 `["*"]`（支持 POST）
- 新增依赖：`python-jose[cryptography]`、`passlib[bcrypt]`

**环境变量：**

- `JWT_SECRET_KEY`（必须设置，生产环境通过环境变量注入）
- `JWT_EXPIRE_DAYS`（可选，默认 7）

**技术方案**：`docs/futu_strategy_docs/futu_strategy_docs/part_d_auth.md`

---

## [v2.4.0] — 2026-05-05

### 个股评分系统重写（Breaking Change）

**从二值判断改为连续映射评分**，6 维度加权求和，满分 100：

| 维度 | 权重 | 算法 |
|------|------|------|
| 周线 RSI6 | 25 | `(70 - rsi) / 50` |
| 日线 MACD 百分位 | 20 | `1 - percentile_rank(252)` |
| 布林带 %B | 15 | `1 - %B` |
| 日线 RSI6 | 20 | `(70 - rsi) / 50` |
| 周线 MACD 百分位 | 10 | `1 - percentile_rank(52)` |
| MA250 偏离 | 10 | `deviation / 0.15` |

**移除的维度**：VIX（需 OpenD）、CNN F&G（需翻墙）、MACD 底背离（不稳定）、恐慌放量（宽基 ETF 无效）

### 新增

- **`trader-analysis score` CLI 命令**：纯本地评分，从 DB 读指标直接计算，不依赖 OpenD
  - 支持 `--backfill N` 回溯 N 天历史评分
- **`GET /api/scores/overview`**：全标的评分速览，按信号分组（STRONG_BUY / BUY / NO_ACTION），支持日期参数
- **`GET /api/scores/latest` 支持 `date` 参数**：查询历史任意交易日的评分
- **`init` 命令支持 `--start` 参数**：按日期范围分段拉取更长历史（已拉取 ~4 年数据）
- VIXY 从标的池移除（40 只标的），VIX 由用户肉眼观察

### API 变更

- **所有接口无数据时统一返回 HTTP 200 + `{data: null, message: "..."}`**（不再返回 404）
- 前端判断逻辑：`if (res.data.data === null)` 展示 message，否则正常渲染
- `breakdown` 字段结构从 `{score, value, triggered}` 改为 `{score, raw, ratio}`

### 前端

- 主题从暗色（黑底金字）切换为白底清爽风格
- 机会速览页标的名称颜色修复（从浅灰改为黑色）

---

## [v2.3.0] — 2026-05-05

### 变更：市场温度评分系统精简（Breaking Change）

**维度从 6 个精简为 3 个**，移除了实际验证中信号价值不足的维度：

| 维度 | 旧权重 | 新权重 | 状态 |
|------|--------|--------|------|
| 日线技术面 | 40% | **50%** | 保留，RSI 改为分档制 |
| 周线技术面 | 20% | **35%** | 保留，新增布林 %B |
| 价格位置 | 20% | **15%** | 保留，阈值收窄 |
| 波动率(VIXY) | 25% | — | **移除**：VIXY contango 衰减不适合评分 |
| 量能确认 | 8% | — | **移除**：宽基 ETF 流动性充裕，量比无信号价值 |
| 避险信号(GLD) | 7% | — | **移除**：流动性危机时黄金同跌产生误导信号 |

### 评分公式调优

- **RSI**：RSI14 → RSI6，评分改为分档制（每 10 点一档，更离散更敏感）
- **周线技术面**：新增布林 %B 子项（3 项取平均：RSI + MACD百分位 + BB%B）
- **价格位置 ATH 回撤**：零分线从 -20% 收窄至 **-15%**（大盘回撤 15% 即极端恐慌）
- **价格位置 MA200 偏离**：映射区间从 ±20% 收窄至 **±15%**

### API 变更（前端需适配）

- `vol_score`、`volume_score`、`safe_haven_score` 字段保留但固定返回 **`null`**
- `gld_price`、`vix_value` 固定返回 **`null`**
- `dimensions` 数组从 6 项减为 **3 项**
- 前端应**过滤 null 维度**，只渲染非 null 的 3 个维度评分条
- 标的指标卡片从 4 列（SPY/QQQ/GLD/VIXY）改为 **2 列（SPY/QQQ）**

### 测试修复

- 所有测试改用 `monkeypatch.setattr` 隔离数据库，不再使用 `os.environ` 模块级设置
- 移除测试中直接 DELETE 真实数据库的代码，防止误清本地数据

### 回测验证

- 评分区间：11.1 ~ 90.4（合理覆盖恐慌到贪婪全区间）
- 2026-03-27（SPY -8.9%）：composite=11.1，极端层触发，建议仓位 97.8%
- 2026-05-04（高位）：composite=82.2，偏贪婪，建议仓位 24.3%
- 极端层在真正暴跌时可触发（之前因维度过多被稀释无法触发）

---

## [v2.2.0] — 2026-05-04

### 新增
- **`/health` 端点**：健康检查，供前端启动时检测后端是否在线
- **市场温度评分系统**（`market_scorer.py`）：6 维度加权评估市场情绪冷热
  - 日线技术面（30%）：SPY/QQQ 的 RSI + MACD 百分位 + 布林 %B
  - 周线技术面（15%）：SPY/QQQ 的周线 RSI + MACD 百分位
  - 波动率（25%）：VIXY 百分位排名（反向，纯百分位方案，自适应 contango 衰减）
  - 价格位置（15%）：52 周位置 + ATH 回撤 + MA200 偏离度
  - 量能确认（8%）：量比 + 5 日量能趋势（结合涨跌方向）
  - 避险信号（7%）：GLD RSI/MACD/BB 全部反向映射
- 仓位映射公式：`target = 90 - composite × 0.8`（常规）；极端层 90%~120%（需 4 条件同时满足）
- CLI 新命令：`trader-analysis temperature` — 计算并打印市场温度评分
- API 新端点：`GET /api/market-temperature`（最新评分）、`GET /api/market-temperature/history`（历史趋势）
- SQLite 新表：`market_score`（扁平字段）+ `market_score_detail`（完整明细 JSON）
- `config.py` 新增 `MARKET_TEMP_CODES`、`MARKET_TEMP_WEIGHTS`、`MARKET_TEMP_VOL_CODE`
- `watchlist.json` 新增 VIXY（VIX 短期期货 ETF，作为波动率代理）
- 测试：`test_market_scorer.py`（31 个）+ `test_market_api.py`（4 个），全部通过

### 设计决策
- 波动率维度使用 VIXY 而非 VIX：Futu 不支持 VIX K 线拉取，VIXY 与 VIX 高度正相关
- VIXY 只用百分位排名（不用绝对值公式）：避免 contango 衰减导致的绝对值失真
- 极端层 VIX>35 条件改为 VIXY 百分位>90%：等效语义，不依赖固定阈值
- 市场温度与个股评分（scorer.py）完全独立，互不影响

### 文档
- `docs/api.md` 更新：新增 market-temperature 相关端点文档
- `position-sizing-strategy.md` 移至 `docs/futu_strategy_docs/futu_strategy_docs/`

---

## [v2.1.0] — 2026-04-23

### 重构
- 删除已废弃模块：`indicators/`、`signals/`、`notify/`、`backtest/`、`strategy/`、`api/`、`examples/`
- 合并 `data/providers.py` + `data/schemas.py` → `futu_strategy/providers.py`（只保留 FutuLiveDataProvider）
- 删除无用数据源：CSVDataProvider、FutuJsonDataProvider、ParquetDataProvider
- CLI 从 3 命令（backtest/signals/serve）改为 4 命令（serve/init/update/run）
- 项目结构精简为：`cli.py` + `futu_strategy/`（完整三层架构）

### 新增
- `config.py`：WATCHLIST 从 `data/watchlist.json` 动态加载（40 只标的，10 个分类）
- `api_server.py`：`/api/watchlist` 返回完整标的信息（name/category/tags/has_data）
- `api_server.py`：指标/评分接口无数据时返回 HTTP 404 + 描述性提示
- `init_history.py`：断点续传（自动跳过已有数据）+ 频率控制（3 秒间隔）+ `--force` 参数
- 新测试套件：test_smoke / test_config / test_storage / test_api（25 个测试）

### 变更
- `__init__.py` 版本号修正为 `0.2.0`（与 pyproject.toml 一致）
- `pyproject.toml` 描述更新为 Futu 量化评分系统
- `.env.example` 更新为当前可用的环境变量

### 文档
- 主技术方案 README.md 重写：删除 v1→v2 迁移指引和已删模块说明，更新项目结构和 CLI 命令
- API 文档 api.md 重写：删除废弃的 api/app.py 服务，更新响应格式
- part_c_api.md 更新 watchlist 响应格式和 404 处理
- part_b_storage.md 更新 init_history 断点续传说明

---

## [v2.0.0] — 2026-04-20

### 架构变更
- futu_strategy 模块从单层架构升级为**三层架构**：后端核心层(Part A) → 持久化存储层(Part B) → API 服务层(Part C)
- 指标计算与评分逻辑解耦：`indicators.py` 只追加数值列，`scorer.py` 只做阈值判断

### 新增
- `futu_strategy/storage.py` — SQLite 持久化层（`kline_indicators` + `score_results` 两张表）
- `futu_strategy/indicators.py` — 配置驱动的通用指标计算函数 `calc_indicators(df, config)`
- `futu_strategy/init_history.py` — 一次性历史数据初始化脚本
- `futu_strategy/daily_update.py` — 每日增量更新脚本（拼接历史后重算指标）
- `futu_strategy/api_server.py` — FastAPI 只读 API（4 个端点，独立于 Futu OpenD）
- `config.py` 新增 `DAILY_INDICATOR_CONFIG`、`WEEKLY_INDICATOR_CONFIG`、`DB_PATH`、`INIT_*_KLINE_COUNT`
- `pyproject.toml` 新增 `scipy` 依赖

### 变更
- `scorer.py` — 不再自行调用 `calc_*` 计算指标，改为从预计算好的 DataFrame 直接读值评分
- `runner.py` — 主流程改为：增量更新存储层 → 从 storage 读指标 → 评分 → 写回存储 → 交易
- 项目版本号从 `0.1.0` 升至 `0.2.0`

### 文档
- 合并旧 `docs/architecture.md` 内容到 `docs/futu_strategy_docs/futu_strategy_docs/README.md`，作为项目整体技术方案
- 删除 `docs/architecture.md`（内容已合并）

---

## [v1.0.0] — 2026-04-14

### 新增
- futu_strategy 模拟盘策略包：9 项指标加权评分（0~100），70 分触发买入，90 分强烈买入
- 数据获取：K 线（日线 250 根 + 周线 60 根）、VIX 快照、CNN Fear & Greed
- 评分引擎：周线 RSI、日线 MACD 背离、VIX、布林带、日线 RSI、CNN F&G、恐慌放量缩量、MA200 偏离、周线 MACD 缩小
- 模拟盘交易执行：限价单下单、持仓检查、防重复买入
- JSONL 日志：评分记录 + 交易记录
- HTTP API 服务：FastAPI 实时指标查询（/v1/indicators/\*、/v1/signals/\*）
- 共享层：OHLCV Schema、多数据源（CSV/JSON/Parquet/Live Futu）、IndicatorSpec 流水线
- 信号模块、策略框架、回测引擎
- CLI 入口（typer）
