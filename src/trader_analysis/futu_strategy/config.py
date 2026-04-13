"""策略配置。

修改此文件以自定义标的列表、仓位大小、评分阈值、OpenD 连接参数等。
"""

from __future__ import annotations

import os

# ── OpenD 连接 ────────────────────────────────────────────────────────────────
OPEND_HOST: str = "127.0.0.1"
OPEND_PORT: int = 11111

# ── 监控标的列表（Futu 格式：市场.代码）────────────────────────────────────────
WATCHLIST: list[str] = [
    "US.AAPL",
    "US.TSLA",
    "HK.00700",
]

# ── 仓位配置 ───────────────────────────────────────────────────────────────────
POSITION_CONFIG: dict = {
    "STRONG_BUY": {
        "type": "fixed_amount",
        "amount_usd": 2000,  # 强烈买入：每次固定金额（USD）
    },
    "BUY": {
        "type": "fixed_amount",
        "amount_usd": 1000,  # 普通买入：每次固定金额（USD）
    },
}

# ── 评分阈值 ───────────────────────────────────────────────────────────────────
SCORE_STRONG_BUY: int = 90
SCORE_BUY: int = 70

# ── K 线拉取配置 ──────────────────────────────────────────────────────────────
DAILY_KLINE_COUNT: int = 250   # 需 ≥ 200 根以计算 MA200，额外 50 根作为缓冲
WEEKLY_KLINE_COUNT: int = 60   # 约 14 个月的周线数据

# ── 外部数据 ───────────────────────────────────────────────────────────────────
# CNN Fear & Greed 非官方接口
CNN_FG_URL: str = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
HTTP_TIMEOUT: int = 10  # 秒

# HTTP 代理（国内访问 CNN 可能需要，设为 None 则不使用）
# 示例：{"https": "http://127.0.0.1:7890"}
HTTP_PROXIES: dict | None = None

# VIX 行情代码；若 US.VIX 不可用可改为 "US.VIXY"
VIX_CODE: str = "US.VIX"

# ── 交易设置 ───────────────────────────────────────────────────────────────────
# 是否允许对已持有标的加仓（金字塔加仓）
ALLOW_PYRAMID: bool = False

# ── 日志路径 ───────────────────────────────────────────────────────────────────
# 默认存放在项目根目录的 logs/ 下（通过环境变量 TA_LOG_DIR 可覆盖）
_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
LOG_DIR: str = os.environ.get("TA_LOG_DIR", os.path.join(_PROJECT_ROOT, "logs"))
SCORE_LOG_FILE: str = os.path.join(LOG_DIR, "score_log.jsonl")
TRADE_LOG_FILE: str = os.path.join(LOG_DIR, "trade_log.jsonl")
