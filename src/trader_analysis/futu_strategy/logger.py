"""日志与审计。

评分结果写入 score_log.jsonl，交易记录写入 trade_log.jsonl。
每行一条 JSON，方便后续解析和审计。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from trader_analysis.futu_strategy import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _ensure_log_dir() -> None:
    os.makedirs(config.LOG_DIR, exist_ok=True)


def log_score(score_result: dict) -> None:
    """将评分结果追加写入 score_log.jsonl。

    score_result 为 scorer.calculate_score() 的返回值。
    """
    _ensure_log_dir()
    record = {
        **score_result,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(config.SCORE_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def log_trade(trade_result: dict) -> None:
    """将交易记录追加写入 trade_log.jsonl。

    trade_result 应包含：code, signal, score, qty, price, order_id, trd_env, status。
    """
    _ensure_log_dir()
    record = {
        **trade_result,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(config.TRADE_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
