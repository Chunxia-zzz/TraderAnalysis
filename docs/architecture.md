 # 项目架构（TraderAnalysis）
 
 本文用于记录仓库当前的模块边界与数据流，便于后续接入实时行情与企业微信推送时保持解耦。
 
 ## 模块与数据流
 
 ```mermaid
 flowchart TD
   cli["CLI (python -m trader_analysis)"] --> provider["data.providers (CSV/Parquet)"]
   provider --> ohlcv["OHLCV DataFrame (规范化 schema)"]
 
   ohlcv --> indicators["indicators (SMA/EMA/RSI/MACD/ATR/BBands)"]
   indicators --> enriched["Enriched DataFrame (含指标列)"]
 
   enriched --> rules["signals.rules (BUY/SELL/HOLD)"]
   rules --> signalSet["SignalSet / signals table"]
 
   signalSet --> backtest["backtest.engine (仓位/交易/权益曲线)"]
   backtest --> report["backtest.report (回撤/Sharpe/胜率等)"]
 
   signalSet -. "后续阶段" .-> notify["notify (Notifier / WeComWebhookNotifier)"]
 ```
 
 ## 关键约定
 
 - **核心约束**：策略/指标/信号是纯计算逻辑，不直接依赖推送、调度、数据拉取方式。
 - **OHLCV 字段**：`timestamp/open/high/low/close/volume/symbol/timeframe`（统一小写）。
 - **信号语义**：每个 bar 都会生成一个信号（默认 HOLD），便于回测与实时对齐。
 
