# TraderAnalysis

量化指标、信号（买入/卖出/持仓）、回测，以及后续可扩展到实时推送（企业微信）。



## 快速开始

### 安装

```bash
python -m venv .venv
.venv\\Scripts\\activate
python -m pip install -U pip
pip install -e ".[dev]"
```

### 准备数据（CSV）

CSV 至少包含这些列（列名不区分大小写，会被规范化为小写）：`timestamp, open, high, low, close, volume`。

时间建议为 ISO8601（例如 `2024-01-01` 或 `2024-01-01 09:30:00`）。

示例文件见 `examples/sample_ohlcv.csv`。
### 跑一次回测（示例策略）

```bash
python -m trader_analysis backtest --data examples/sample_ohlcv.csv --strategy ma_cross
```

### 导出信号

```bash
python -m trader_analysis signals --data examples/sample_ohlcv.csv --strategy rsi_reversal --out signals.csv
```

## 数据与扩展点

- **数据源**：`trader_analysis.data.providers`（目前支持 CSV；可选 Parquet）
- **指标**：`trader_analysis.indicators.builtins`
- **信号**：`trader_analysis.signals.rules`（BUY/SELL/HOLD）
- **回测**：`trader_analysis.backtest.engine`
- **通知**：`trader_analysis.notify`（预留接口；后续接企业微信 Webhook）

## 架构

见 [`docs/architecture.md`](docs/architecture.md)（含 Mermaid 架构图）。

## API 服务（给前端调用）

### 启动服务

```bash
python -m trader_analysis serve --host 0.0.0.0 --port 8000
```

### 可选环境变量（实时刷新配置）

- `TA_DATA_PATH`：数据文件路径（默认 `examples/sample_ohlcv.csv`）
- `TA_SYMBOL`：标的（默认 `DEMO`）
- `TA_TIMEFRAME`：周期（默认 `1D`）
- `TA_STRATEGY`：策略（`ma_cross` 或 `rsi_reversal`）
- `TA_REFRESH_SECONDS`：刷新秒数（默认 `5`）

### 接口

- `GET /health`：服务健康与刷新状态
- `GET /v1/indicators/latest`：最新一条指标数据
- `GET /v1/indicators/history?limit=100`：最近 N 条指标数据
- `GET /v1/signals/latest`：最新一条信号（BUY/SELL/HOLD）