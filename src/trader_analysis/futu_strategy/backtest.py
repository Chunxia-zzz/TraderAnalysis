"""信号回测引擎。

支持三种策略模式：
- hold: 评分达标买入，固定持有N天卖出（买入持有）
- swing: 评分达标买入，评分回落至exit_threshold时卖出（波段操作）
- trend: 评分达标买入，收盘价跌破MA时卖出（趋势跟踪，适合强势股）

纯只读——不修改任何数据表，结果仅内存返回。

用法：
    from trader_analysis.futu_strategy.backtest import run_backtest, BacktestParams
    # 买入持有
    result = run_backtest(BacktestParams(code="US.SNDK", mode="hold", threshold=40, holding_days=10))
    # 波段操作
    result = run_backtest(BacktestParams(code="US.SNDK", mode="swing", threshold=60, exit_threshold=30))
    # 趋势跟踪
    result = run_backtest(BacktestParams(code="US.SNDK", mode="trend", threshold=40, trail_ma="ma5"))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median, stdev

from trader_analysis.futu_strategy.storage import (
    query_all_scores,
    query_close_prices,
    query_ema_ribbon_data,
    query_price_and_ma,
    query_trading_dates,
)


@dataclass
class BacktestParams:
    code: str
    mode: str = "hold"  # hold | swing | trend | ribbon_long | ribbon_short
    threshold: int = 40
    # hold 模式参数
    holding_days: int = 10
    # swing 模式参数
    exit_threshold: int = 30  # 评分回落至此卖出
    max_holding_days: int = 120  # swing/trend 模式最大持有天数（防止永远不卖）
    # trend 模式参数
    trail_ma: str = "ma5"  # 跟踪止盈均线: ma5/ma10/ma20
    # 买入确认
    entry_confirm: str = "none"  # none | above_ma5 (等站上MA5再买)
    # 通用参数
    cooldown: str = "holding"  # none | holding | custom
    cooldown_days: int | None = None
    start_date: str | None = None
    end_date: str | None = None


@dataclass
class Trade:
    signal_date: str
    entry_price: float
    exit_date: str | None
    exit_price: float | None
    return_pct: float | None
    holding_days: int | None  # 实际持有天数
    entry_score: float
    exit_score: float | None  # swing 模式卖出时的评分
    exit_reason: str | None  # hold/score_drop/max_holding/incomplete
    signal: str
    status: str  # complete | incomplete


def _apply_cooldown(signals: list[dict], params: BacktestParams, date_index: dict[str, int]) -> list[dict]:
    """应用冷却期去重。"""
    if params.cooldown == "none":
        return signals

    if params.mode == "hold":
        cooldown_days = params.holding_days if params.cooldown == "holding" else (params.cooldown_days or params.holding_days)
    else:
        # swing 模式：冷却期默认用 max_holding_days 或 custom
        cooldown_days = params.cooldown_days or params.max_holding_days if params.cooldown == "custom" else 0

    # swing + holding 模式: 冷却期在交易完成后动态处理，这里先不过滤
    if params.mode == "swing" and params.cooldown == "holding":
        return signals

    if cooldown_days <= 0:
        return signals

    filtered = []
    last_entry_idx = -999

    for s in signals:
        idx = date_index.get(s["date"])
        if idx is None:
            continue
        if idx - last_entry_idx >= cooldown_days:
            filtered.append(s)
            last_entry_idx = idx

    return filtered


def _apply_entry_confirm(
    signals: list[dict],
    params: BacktestParams,
    trading_dates: list[str],
    date_index: dict[str, int],
    price_ma_data: dict[str, dict],
) -> list[dict]:
    """应用买入确认：评分达标后，等收盘站上MA5那天才确认买入。

    将 signal 的 date 替换为确认日（站上MA5那天），entry 用确认日的收盘价。
    """
    if params.entry_confirm == "none":
        return signals

    confirmed = []
    for s in signals:
        entry_idx = date_index.get(s["date"])
        if entry_idx is None:
            continue

        # 从信号日+1开始，找收盘 > MA5 的日期（最多找 max_holding_days 天）
        search_limit = min(params.max_holding_days, 60)
        for offset in range(1, search_limit + 1):
            check_idx = entry_idx + offset
            if check_idx >= len(trading_dates):
                break
            check_date = trading_dates[check_idx]
            day_data = price_ma_data.get(check_date)
            if not day_data or day_data["ma"] is None:
                continue
            if day_data["close"] > day_data["ma"]:
                # 确认反转：用这天作为买入日
                confirmed.append({
                    **s,
                    "date": check_date,
                    "original_signal_date": s["date"],
                })
                break

    return confirmed


def _calculate_summary(trades: list[Trade]) -> dict:
    """计算汇总统计指标。"""
    completed = [t for t in trades if t.status == "complete"]

    if not completed:
        return {
            "total_signals": len(trades),
            "completed_trades": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0.0,
            "avg_return_pct": 0.0,
            "median_return_pct": 0.0,
            "max_return_pct": 0.0,
            "min_return_pct": 0.0,
            "total_return_pct": 0.0,
            "avg_holding_days": 0.0,
            "sharpe_like": 0.0,
            "profit_factor": 0.0,
        }

    returns = [t.return_pct for t in completed]
    holding_days_list = [t.holding_days for t in completed if t.holding_days]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    avg_ret = sum(returns) / len(returns)
    std_ret = stdev(returns) if len(returns) > 1 else 0.001
    total_profit = sum(wins) if wins else 0
    total_loss = abs(sum(losses)) if losses else 0.001

    return {
        "total_signals": len(trades),
        "completed_trades": len(completed),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / len(completed) * 100, 1),
        "avg_return_pct": round(avg_ret, 2),
        "median_return_pct": round(median(returns), 2),
        "max_return_pct": round(max(returns), 2),
        "min_return_pct": round(min(returns), 2),
        "total_return_pct": round(sum(returns), 2),
        "avg_holding_days": round(sum(holding_days_list) / len(holding_days_list), 1) if holding_days_list else 0,
        "sharpe_like": round(avg_ret / std_ret, 2) if std_ret > 0 else 0.0,
        "profit_factor": round(total_profit / total_loss, 2) if total_loss > 0 else 999.0,
    }


def _run_hold_mode(params: BacktestParams, scores: list[dict], prices: dict, trading_dates: list, date_index: dict, price_ma5: dict | None = None) -> list[Trade]:
    """策略A: 买入持有模式。"""
    signal_dates = [s for s in scores if s["total_score"] >= params.threshold]
    if price_ma5 and params.entry_confirm == "above_ma5":
        signal_dates = _apply_entry_confirm(signal_dates, params, trading_dates, date_index, price_ma5)
    filtered_signals = _apply_cooldown(signal_dates, params, date_index)

    trades: list[Trade] = []
    for signal in filtered_signals:
        entry_date = signal["date"]
        entry_price = prices.get(entry_date)
        if entry_price is None:
            continue

        entry_idx = date_index.get(entry_date)
        if entry_idx is None:
            continue

        exit_idx = entry_idx + params.holding_days
        if exit_idx >= len(trading_dates):
            trades.append(Trade(
                signal_date=entry_date, entry_price=round(entry_price, 2),
                exit_date=None, exit_price=None, return_pct=None,
                holding_days=None, entry_score=signal["total_score"],
                exit_score=None, exit_reason="incomplete",
                signal=signal["signal"], status="incomplete",
            ))
            continue

        exit_date = trading_dates[exit_idx]
        exit_price = prices.get(exit_date)
        if exit_price is None:
            trades.append(Trade(
                signal_date=entry_date, entry_price=round(entry_price, 2),
                exit_date=exit_date, exit_price=None, return_pct=None,
                holding_days=params.holding_days, entry_score=signal["total_score"],
                exit_score=None, exit_reason="incomplete",
                signal=signal["signal"], status="incomplete",
            ))
            continue

        return_pct = round((exit_price - entry_price) / entry_price * 100, 2)
        trades.append(Trade(
            signal_date=entry_date, entry_price=round(entry_price, 2),
            exit_date=exit_date, exit_price=round(exit_price, 2),
            return_pct=return_pct, holding_days=params.holding_days,
            entry_score=signal["total_score"], exit_score=None,
            exit_reason="hold", signal=signal["signal"], status="complete",
        ))

    return trades


def _run_swing_mode(params: BacktestParams, scores: list[dict], prices: dict, trading_dates: list, date_index: dict, price_ma5: dict | None = None) -> list[Trade]:
    """策略B: 波段操作模式。评分高时买入，评分回落时卖出。"""
    # 构建日期→评分映射
    score_by_date = {s["date"]: s for s in scores}

    signal_dates = [s for s in scores if s["total_score"] >= params.threshold]
    if price_ma5 and params.entry_confirm == "above_ma5":
        signal_dates = _apply_entry_confirm(signal_dates, params, trading_dates, date_index, price_ma5)
    filtered_signals = _apply_cooldown(signal_dates, params, date_index)

    trades: list[Trade] = []
    last_exit_idx = -1  # swing + holding 冷却

    for signal in filtered_signals:
        entry_date = signal["date"]
        entry_price = prices.get(entry_date)
        entry_idx = date_index.get(entry_date)
        if entry_price is None or entry_idx is None:
            continue

        # swing + holding: 上一笔卖出后才能开新仓
        if params.cooldown == "holding" and entry_idx <= last_exit_idx:
            continue

        # 寻找卖出点：从买入日+1开始，找评分 <= exit_threshold 的日期
        exit_date = None
        exit_price = None
        exit_score = None
        exit_reason = None
        actual_holding = None

        for offset in range(1, params.max_holding_days + 1):
            check_idx = entry_idx + offset
            if check_idx >= len(trading_dates):
                break
            check_date = trading_dates[check_idx]
            check_score_data = score_by_date.get(check_date)

            if check_score_data and check_score_data["total_score"] <= params.exit_threshold:
                exit_date = check_date
                exit_price = prices.get(check_date)
                exit_score = check_score_data["total_score"]
                exit_reason = "score_drop"
                actual_holding = offset
                break

        # 达到最大持有天数仍未触发卖出 → 强制卖出
        if exit_date is None:
            max_idx = entry_idx + params.max_holding_days
            if max_idx < len(trading_dates):
                exit_date = trading_dates[max_idx]
                exit_price = prices.get(exit_date)
                exit_score_data = score_by_date.get(exit_date)
                exit_score = exit_score_data["total_score"] if exit_score_data else None
                exit_reason = "max_holding"
                actual_holding = params.max_holding_days
            else:
                # 数据不够
                trades.append(Trade(
                    signal_date=entry_date, entry_price=round(entry_price, 2),
                    exit_date=None, exit_price=None, return_pct=None,
                    holding_days=None, entry_score=signal["total_score"],
                    exit_score=None, exit_reason="incomplete",
                    signal=signal["signal"], status="incomplete",
                ))
                continue

        if exit_price is None:
            trades.append(Trade(
                signal_date=entry_date, entry_price=round(entry_price, 2),
                exit_date=exit_date, exit_price=None, return_pct=None,
                holding_days=actual_holding, entry_score=signal["total_score"],
                exit_score=exit_score, exit_reason="incomplete",
                signal=signal["signal"], status="incomplete",
            ))
            continue

        return_pct = round((exit_price - entry_price) / entry_price * 100, 2)
        trades.append(Trade(
            signal_date=entry_date, entry_price=round(entry_price, 2),
            exit_date=exit_date, exit_price=round(exit_price, 2),
            return_pct=return_pct, holding_days=actual_holding,
            entry_score=signal["total_score"], exit_score=exit_score,
            exit_reason=exit_reason, signal=signal["signal"], status="complete",
        ))
        last_exit_idx = date_index.get(exit_date, entry_idx)

    return trades


def _run_trend_mode(params: BacktestParams, scores: list[dict], prices: dict, trading_dates: list, date_index: dict, price_ma5: dict | None = None) -> list[Trade]:
    """策略C: 趋势跟踪模式。评分达标买入，收盘跌破MA时卖出。"""
    # 获取 close + MA 数据（卖出用的 trail_ma）
    price_ma = query_price_and_ma(params.code, params.trail_ma, params.start_date, params.end_date)

    signal_dates = [s for s in scores if s["total_score"] >= params.threshold]
    if price_ma5 and params.entry_confirm == "above_ma5":
        signal_dates = _apply_entry_confirm(signal_dates, params, trading_dates, date_index, price_ma5)
    filtered_signals = _apply_cooldown(signal_dates, params, date_index)

    trades: list[Trade] = []
    last_exit_idx = -1

    for signal in filtered_signals:
        entry_date = signal["date"]
        entry_price = prices.get(entry_date)
        entry_idx = date_index.get(entry_date)
        if entry_price is None or entry_idx is None:
            continue

        # 冷却: 上一笔卖出后才能开新仓
        if params.cooldown == "holding" and entry_idx <= last_exit_idx:
            continue

        # 寻找卖出点：从买入日+1开始，找收盘价 < MA 的日期
        exit_date = None
        exit_price = None
        exit_reason = None
        actual_holding = None

        for offset in range(1, params.max_holding_days + 1):
            check_idx = entry_idx + offset
            if check_idx >= len(trading_dates):
                break
            check_date = trading_dates[check_idx]
            day_data = price_ma.get(check_date)
            if not day_data or day_data["ma"] is None:
                continue

            # 收盘价跌破 MA → 卖出
            if day_data["close"] < day_data["ma"]:
                exit_date = check_date
                exit_price = day_data["close"]
                exit_reason = f"below_{params.trail_ma}"
                actual_holding = offset
                break

        # 达到最大持有天数仍未跌破 MA → 强制卖出
        if exit_date is None:
            max_idx = entry_idx + params.max_holding_days
            if max_idx < len(trading_dates):
                exit_date = trading_dates[max_idx]
                exit_price = prices.get(exit_date)
                exit_reason = "max_holding"
                actual_holding = params.max_holding_days
            else:
                trades.append(Trade(
                    signal_date=entry_date, entry_price=round(entry_price, 2),
                    exit_date=None, exit_price=None, return_pct=None,
                    holding_days=None, entry_score=signal["total_score"],
                    exit_score=None, exit_reason="incomplete",
                    signal=signal["signal"], status="incomplete",
                ))
                continue

        if exit_price is None:
            trades.append(Trade(
                signal_date=entry_date, entry_price=round(entry_price, 2),
                exit_date=exit_date, exit_price=None, return_pct=None,
                holding_days=actual_holding, entry_score=signal["total_score"],
                exit_score=None, exit_reason="incomplete",
                signal=signal["signal"], status="incomplete",
            ))
            continue

        return_pct = round((exit_price - entry_price) / entry_price * 100, 2)
        trades.append(Trade(
            signal_date=entry_date, entry_price=round(entry_price, 2),
            exit_date=exit_date, exit_price=round(exit_price, 2),
            return_pct=return_pct, holding_days=actual_holding,
            entry_score=signal["total_score"], exit_score=None,
            exit_reason=exit_reason, signal=signal["signal"], status="complete",
        ))
        last_exit_idx = date_index.get(exit_date, entry_idx)

    return trades


def _run_ribbon_long_mode(params: BacktestParams, ema_data: list[dict]) -> list[Trade]:
    """策略D: EMA 飘带多头模式。空转多买入，多转空卖出。"""
    trades: list[Trade] = []

    # 找所有翻转点
    bull_dates: list[str] = []   # 空转多（入场）
    bear_dates: list[str] = []   # 多转空（出场）
    for i in range(1, len(ema_data)):
        prev = ema_data[i - 1]
        cur = ema_data[i]
        prev_bull = prev["ema5"] >= prev["ema30"]
        cur_bull = cur["ema5"] >= cur["ema30"]
        if not prev_bull and cur_bull:
            bull_dates.append(cur["date"])
        elif prev_bull and not cur_bull:
            bear_dates.append(cur["date"])

    close_by_date = {d["date"]: d["close"] for d in ema_data}

    for entry_date in bull_dates:
        entry_price = close_by_date.get(entry_date)
        if entry_price is None:
            continue
        # 找下一个多转空日期
        exit_date = next((d for d in bear_dates if d > entry_date), None)
        if exit_date is None:
            trades.append(Trade(
                signal_date=entry_date, entry_price=round(entry_price, 2),
                exit_date=None, exit_price=None, return_pct=None,
                holding_days=None, entry_score=0.0, exit_score=None,
                exit_reason="incomplete", signal="RIBBON_LONG", status="incomplete",
            ))
            continue
        exit_price = close_by_date.get(exit_date)
        if exit_price is None:
            continue
        return_pct = round((exit_price - entry_price) / entry_price * 100, 2)
        trades.append(Trade(
            signal_date=entry_date, entry_price=round(entry_price, 2),
            exit_date=exit_date, exit_price=round(exit_price, 2),
            return_pct=return_pct, holding_days=None,
            entry_score=0.0, exit_score=None,
            exit_reason="ribbon_flip_short", signal="RIBBON_LONG", status="complete",
        ))

    return trades


def _run_ribbon_short_mode(params: BacktestParams, ema_data: list[dict]) -> list[Trade]:
    """策略E: EMA 飘带空头模式。多转空做空，空转多平空。收益率 = (入场价 - 出场价) / 入场价。"""
    trades: list[Trade] = []

    bull_dates: list[str] = []   # 空转多（平空）
    bear_dates: list[str] = []   # 多转空（入场做空）
    for i in range(1, len(ema_data)):
        prev = ema_data[i - 1]
        cur = ema_data[i]
        prev_bull = prev["ema5"] >= prev["ema30"]
        cur_bull = cur["ema5"] >= cur["ema30"]
        if not prev_bull and cur_bull:
            bull_dates.append(cur["date"])
        elif prev_bull and not cur_bull:
            bear_dates.append(cur["date"])

    close_by_date = {d["date"]: d["close"] for d in ema_data}

    for entry_date in bear_dates:
        entry_price = close_by_date.get(entry_date)
        if entry_price is None:
            continue
        # 找下一个空转多日期（平空）
        exit_date = next((d for d in bull_dates if d > entry_date), None)
        if exit_date is None:
            trades.append(Trade(
                signal_date=entry_date, entry_price=round(entry_price, 2),
                exit_date=None, exit_price=None, return_pct=None,
                holding_days=None, entry_score=0.0, exit_score=None,
                exit_reason="incomplete", signal="RIBBON_SHORT", status="incomplete",
            ))
            continue
        exit_price = close_by_date.get(exit_date)
        if exit_price is None:
            continue
        # 空头收益：价格下跌为正收益
        return_pct = round((entry_price - exit_price) / entry_price * 100, 2)
        trades.append(Trade(
            signal_date=entry_date, entry_price=round(entry_price, 2),
            exit_date=exit_date, exit_price=round(exit_price, 2),
            return_pct=return_pct, holding_days=None,
            entry_score=0.0, exit_score=None,
            exit_reason="ribbon_flip_long", signal="RIBBON_SHORT", status="complete",
        ))

    return trades


def run_backtest(params: BacktestParams) -> dict:
    """执行单股信号回测。

    Parameters
    ----------
    params : BacktestParams
        mode="hold": 买入持有策略
        mode="swing": 波段操作策略

    Returns
    -------
    dict with keys: code, params, summary, trades
    """
    mode = params.mode
    if mode == "signal_exit":
        mode = "swing"
    elif mode == "trailing_stop":
        mode = "trend"

    # ── EMA 飘带策略（不需要评分数据）──────────────────────────────
    if mode in ("ribbon_long", "ribbon_short"):
        ema_data = query_ema_ribbon_data(params.code, params.start_date, params.end_date)
        if not ema_data:
            return {"data": None, "message": f"{params.code} 暂无 EMA 数据，请先运行 init/update"}
        if mode == "ribbon_long":
            trades = _run_ribbon_long_mode(params, ema_data)
        else:
            trades = _run_ribbon_short_mode(params, ema_data)
        summary = _calculate_summary(trades)
        actual_start = ema_data[0]["date"]
        actual_end = ema_data[-1]["date"]
        return {
            "code": params.code,
            "mode": mode,
            "params": {"mode": mode, "start_date": actual_start, "end_date": actual_end},
            "summary": summary,
            "trades": [
                {
                    "signal_date": t.signal_date,
                    "entry_price": t.entry_price,
                    "exit_date": t.exit_date,
                    "exit_price": t.exit_price,
                    "return_pct": t.return_pct,
                    "holding_days": t.holding_days,
                    "entry_score": t.entry_score,
                    "exit_score": t.exit_score,
                    "exit_reason": t.exit_reason,
                    "signal": t.signal,
                    "status": t.status,
                }
                for t in trades
            ],
        }

    # ── 评分策略 ──────────────────────────────────────────────────
    # Step 1: 获取数据
    scores = query_all_scores(params.code, params.start_date, params.end_date)
    if not scores:
        return {"data": None, "message": f"{params.code} 暂无评分数据"}

    prices = query_close_prices(params.code, params.start_date, params.end_date)
    trading_dates = query_trading_dates(params.code, params.start_date, params.end_date)

    if not prices or not trading_dates:
        return {"data": None, "message": f"{params.code} 暂无日线数据"}

    # Step 2: 构建交易日索引
    date_index = {d: i for i, d in enumerate(trading_dates)}

    # Step 2.5: 加载 MA5 数据（entry_confirm 或 trend 模式需要）
    price_ma5 = None
    if params.entry_confirm == "above_ma5":
        price_ma5 = query_price_and_ma(params.code, "ma5", params.start_date, params.end_date)

    # Step 3: 按模式执行
    if mode == "swing":
        trades = _run_swing_mode(params, scores, prices, trading_dates, date_index, price_ma5)
    elif mode == "trend":
        trades = _run_trend_mode(params, scores, prices, trading_dates, date_index, price_ma5)
    else:
        trades = _run_hold_mode(params, scores, prices, trading_dates, date_index, price_ma5)

    # Step 4: 汇总统计
    summary = _calculate_summary(trades)

    # 确定实际日期范围
    actual_start = trading_dates[0] if trading_dates else None
    actual_end = trading_dates[-1] if trading_dates else None

    return {
        "code": params.code,
        "mode": params.mode,
        "params": {
            "mode": params.mode,
            "threshold": params.threshold,
            "holding_days": params.holding_days if params.mode == "hold" else None,
            "exit_threshold": params.exit_threshold if params.mode == "swing" else None,
            "max_holding_days": params.max_holding_days if params.mode in ("swing", "trend") else None,
            "trail_ma": params.trail_ma if params.mode == "trend" else None,
            "entry_confirm": params.entry_confirm,
            "cooldown": params.cooldown,
            "start_date": actual_start,
            "end_date": actual_end,
        },
        "summary": summary,
        "trades": [
            {
                "signal_date": t.signal_date,
                "entry_price": t.entry_price,
                "exit_date": t.exit_date,
                "exit_price": t.exit_price,
                "return_pct": t.return_pct,
                "holding_days": t.holding_days,
                "entry_score": t.entry_score,
                "exit_score": t.exit_score,
                "exit_reason": t.exit_reason,
                "signal": t.signal,
                "status": t.status,
            }
            for t in trades
        ],
    }
