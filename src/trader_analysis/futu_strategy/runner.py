"""策略主入口。

接收标的列表，依次：拉取 K 线 → 计算指标 → 评分 → 交易 → 记录日志。

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

from trader_analysis.futu_strategy import config
from trader_analysis.futu_strategy.data_fetcher import check_kl_quota, fetch_daily, fetch_weekly
from trader_analysis.futu_strategy.external_data import get_fear_greed, get_vix, reset_cache
from trader_analysis.futu_strategy.logger import log_score
from trader_analysis.futu_strategy.scorer import calculate_score
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

        # ── K 线额度预检（整批次检查一次）────────────────────────────────────
        check_kl_quota(quote_ctx, codes)

        # ── 全局数据（VIX / F&G 各只拉取一次）───────────────────────────────
        reset_cache()
        vix = get_vix(quote_ctx)
        fg = get_fear_greed()
        logger.info(f"全局指标：VIX={vix}, F&G={fg}")

        # ── 逐标的评分与交易 ──────────────────────────────────────────────────
        for code in codes:
            try:
                logger.info(f"── 开始处理 {code} ──")
                daily_df = fetch_daily(quote_ctx, code)
                weekly_df = fetch_weekly(quote_ctx, code)

                result = calculate_score(code, daily_df, weekly_df, vix=vix, fg=fg)
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
