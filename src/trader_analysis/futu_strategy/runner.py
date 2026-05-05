"""策略主入口（v2.0）。

执行流程：
  1. 增量更新存储层（daily_update）
  2. 从 storage 读取已计算好的指标
  3. 评分 → 写入评分结果 → 交易 → 记录日志

运行方式：
  python -m trader_analysis.futu_strategy
  python -m trader_analysis.futu_strategy --codes US.AAPL US.TSLA HK.00700

定时调度（推荐美股次日 06:00 北京时间，此时日线数据已稳定）：
  Windows 任务计划程序 / Linux crontab:
      0 6 * * * python -m trader_analysis.futu_strategy
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

from trader_analysis.futu_strategy import config
from trader_analysis.futu_strategy.daily_update import run_update
from trader_analysis.futu_strategy.logger import log_score
from trader_analysis.futu_strategy.scorer import calculate_score
from trader_analysis.futu_strategy.storage import init_db, query_recent, upsert_score
from trader_analysis.futu_strategy.trade_executor import execute_trade

logger = logging.getLogger(__name__)


def run_strategy(codes: list[str]) -> None:
    """对 codes 列表中每个标的执行完整的评分→交易流程。

    OpenQuoteContext 和 OpenSecTradeContext 在循环外创建并复用，
    避免频繁建连导致超时。
    """
    try:
        from futu import OpenQuoteContext, OpenSecTradeContext  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError("futu-api 未安装，请执行: pip install futu-api") from exc

    init_db()

    quote_ctx = OpenQuoteContext(host=config.OPEND_HOST, port=config.OPEND_PORT)
    trd_ctx = OpenSecTradeContext(host=config.OPEND_HOST, port=config.OPEND_PORT)

    try:
        # ── 获取模拟账户 ID（全程复用）────────────────────────────────────────
        ret, acc_df = trd_ctx.get_acc_list()
        if ret != 0:
            raise RuntimeError(f"获取账户列表失败: {acc_df}")

        sim_accs = acc_df[acc_df["trd_env"] == "SIMULATE"]
        if sim_accs.empty:
            raise RuntimeError("未找到模拟账户，请确认富途已登录并开启模拟盘")
        acc_id = int(sim_accs.iloc[0]["acc_id"])
        logger.info(f"使用模拟账户 acc_id={acc_id}")

        # ── 1. 增量更新存储层 ─────────────────────────────────────────────────
        logger.info("开始增量更新存储层...")
        run_update(codes, quote_ctx=quote_ctx)

        # ── 2. 逐标的评分与交易 ──────────────────────────────────────────────
        today = date.today().isoformat()
        for code in codes:
            try:
                logger.info(f"── 开始处理 {code} ──")

                # 从存储层读取已含指标列的 DataFrame
                daily_df = query_recent(code, "1d", limit=300)
                weekly_df = query_recent(code, "1w", limit=60)

                if daily_df.empty or weekly_df.empty:
                    logger.warning(f"{code} 存储层无数据，跳过（请先运行 init_history）")
                    continue

                result = calculate_score(code, daily_df, weekly_df)

                # 写入评分结果到存储层
                upsert_score(code, today, result)
                log_score(result)

                triggered = [
                    k for k, v in result["breakdown"].items() if v["triggered"]
                ]
                logger.info(
                    f"{code}  总分={result['total_score']}  信号={result['signal']}"
                    f"  触发项={triggered}"
                )

                if result["signal"] in ("BUY", "STRONG_BUY"):
                    execute_trade(result, acc_id, trd_ctx, quote_ctx)

            except Exception as exc:
                logger.warning(f"{code} 处理异常，跳过：{exc}")

    finally:
        quote_ctx.close()
        trd_ctx.close()
        logger.info("所有连接已关闭")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="富途模拟盘买入策略",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：python -m trader_analysis.futu_strategy --codes US.AAPL US.TSLA",
    )
    parser.add_argument(
        "--codes",
        nargs="+",
        default=config.WATCHLIST,
        metavar="CODE",
        help="标的代码列表（默认使用 config.WATCHLIST）",
    )
    args = parser.parse_args()
    run_strategy(args.codes)


if __name__ == "__main__":
    main()
