"""网格交易主引擎。

长驻进程，订阅实时行情，价格穿越网格线时自动下单。

用法：
    from trader_analysis.futu_strategy.grid_trader.engine import GridEngine
    engine = GridEngine(config_id=1)
    engine.start()  # 阻塞，Ctrl+C 停止
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import datetime

from trader_analysis.futu_strategy import config as app_config
from trader_analysis.futu_strategy.grid_trader import state_manager
from trader_analysis.futu_strategy.grid_trader.executor import place_grid_order
from trader_analysis.futu_strategy.grid_trader.models import GridConfig, GridState, Signal
from trader_analysis.futu_strategy.grid_trader.risk_control import check_risk, is_trading_hours
from trader_analysis.futu_strategy.grid_trader.strategy import (
    calculate_grid_lines,
    detect_crossing,
    should_execute,
)

logger = logging.getLogger("grid_trader")


class GridEngine:
    """网格交易引擎。"""

    def __init__(self, config_id: int):
        state_manager.init_grid_tables()

        self.cfg = state_manager.get_config(config_id)
        if not self.cfg:
            raise ValueError(f"Grid config #{config_id} not found")

        self.state = state_manager.get_state(config_id)
        self.grid_lines = calculate_grid_lines(self.cfg)
        self.prev_price: float | None = None
        self._running = False
        self._quote_ctx = None
        self._trd_ctx = None

    def start(self) -> None:
        """启动引擎：连接 OpenD、订阅行情、进入事件循环。"""
        from futu import OpenQuoteContext, OpenSecTradeContext, SubType, TrdEnv, TrdMarket

        logger.info(f"Starting grid engine #{self.cfg.id}: {self.cfg.code} [{self.cfg.env}]")
        logger.info(f"Grid lines ({len(self.grid_lines)}): {self.grid_lines}")

        if self.cfg.env == "live":
            logger.warning("*** LIVE TRADING MODE - REAL MONEY AT RISK ***")

        # 连接
        self._quote_ctx = OpenQuoteContext(host=app_config.OPEND_HOST, port=app_config.OPEND_PORT)
        trd_env = TrdEnv.SIMULATE if self.cfg.env == "simulate" else TrdEnv.REAL
        self._trd_ctx = OpenSecTradeContext(
            host=app_config.OPEND_HOST,
            port=app_config.OPEND_PORT,
            filter_trdmarket=TrdMarket.US,
        )

        # 订阅行情
        from trader_analysis.futu_strategy.grid_trader.quote_handler import create_quote_handler

        handler = create_quote_handler(self)
        self._quote_ctx.set_handler(handler)
        ret, msg = self._quote_ctx.subscribe([self.cfg.code], [SubType.QUOTE])
        if ret != 0:
            raise RuntimeError(f"Subscribe failed: {msg}")

        # 更新状态
        state_manager.update_config_status(self.cfg.id, "running")
        self._running = True

        # 注册信号处理
        signal.signal(signal.SIGINT, self._handle_stop)
        signal.signal(signal.SIGTERM, self._handle_stop)

        logger.info("Engine running. Waiting for price updates... (Ctrl+C to stop)")

        # 事件循环（行情通过回调推送，这里只需保持进程存活）
        try:
            while self._running:
                # 检查是否被外部 grid-stop 设为 stopped
                cfg = state_manager.get_config(self.cfg.id)
                if cfg and cfg.status == "stopped":
                    logger.info("External stop signal detected")
                    break
                time.sleep(1)
        finally:
            self.stop()

    def stop(self) -> None:
        """停止引擎：保存状态、断开连接。"""
        self._running = False
        logger.info("Stopping grid engine...")

        # 保存状态
        state_manager.save_state(self.state)
        state_manager.update_config_status(self.cfg.id, "stopped")

        # 断开连接
        if self._quote_ctx:
            self._quote_ctx.close()
            self._quote_ctx = None
        if self._trd_ctx:
            self._trd_ctx.close()
            self._trd_ctx = None

        logger.info("Engine stopped.")

    def on_price_update(self, code: str, price: float) -> None:
        """行情回调入口：核心决策逻辑。"""
        if code != self.cfg.code:
            return

        self.state.last_price = price

        # 首次收到价格，记录但不触发
        if self.prev_price is None:
            self.prev_price = price
            logger.info(f"[INIT] First price: ${price:.2f}")
            state_manager.save_state(self.state)
            return

        # 交易时段检查
        if not is_trading_hours(self.cfg):
            self.prev_price = price
            return

        # 检测穿越
        sig = detect_crossing(price, self.prev_price, self.grid_lines)
        self.prev_price = price

        if sig is None:
            return

        # 网格状态检查
        if not should_execute(sig, self.state.grid_status):
            logger.debug(f"[SKIP] {sig.direction} level={sig.grid_level} (already {self.state.grid_status.get(str(sig.grid_level), 'empty')})")
            return

        # 风控检查
        passed, reason = check_risk(self.state, self.cfg, sig.direction)
        if not passed:
            logger.warning(f"[RISK] {sig.direction} blocked: {reason}")
            return

        # 执行下单
        self._execute_signal(sig, price)

    def _execute_signal(self, sig: Signal, current_price: float) -> None:
        """执行交易信号。"""
        logger.info(
            f"[SIGNAL] {self.cfg.code} price=${current_price:.2f} "
            f"crossed grid_level={sig.grid_level} (${sig.grid_price:.2f}) → {sig.direction}"
        )

        # 下单（用网格线价格作为限价）
        order_id = place_grid_order(
            self._trd_ctx,
            self.cfg.code,
            sig.direction,
            self.cfg.order_qty,
            sig.grid_price,
            self.cfg.env,
        )

        # 记录订单
        status = "submitted" if order_id else "failed"
        row_id = state_manager.insert_order(
            config_id=self.cfg.id,
            code=self.cfg.code,
            env=self.cfg.env,
            direction=sig.direction,
            grid_level=sig.grid_level,
            grid_price=sig.grid_price,
            order_qty=self.cfg.order_qty,
            order_id=order_id,
            status=status,
        )

        # 简化处理：假设立即成交（模拟盘通常秒成交）
        if order_id:
            fill_price = sig.grid_price
            pnl = None

            if sig.direction == "BUY":
                # 更新持仓
                total_cost = self.state.cost_basis * self.state.current_position + fill_price * self.cfg.order_qty
                self.state.current_position += self.cfg.order_qty
                self.state.cost_basis = total_cost / self.state.current_position if self.state.current_position > 0 else 0
                # 更新网格状态
                self.state.grid_status[str(sig.grid_level)] = "bought"
            else:
                # SELL: 计算盈亏
                pnl = round((fill_price - self.state.cost_basis) * self.cfg.order_qty, 2)
                self.state.current_position -= self.cfg.order_qty
                self.state.daily_pnl += pnl
                if self.state.current_position <= 0:
                    self.state.cost_basis = 0.0
                    self.state.current_position = 0
                # 更新网格状态
                self.state.grid_status[str(sig.grid_level)] = "empty"

            self.state.daily_trades += 1

            # 更新订单成交
            state_manager.update_order_fill(row_id, fill_price, self.cfg.order_qty, pnl)

            if pnl is not None:
                logger.info(f"[FILL] {sig.direction} {self.cfg.order_qty}@{fill_price:.2f} pnl=${pnl:.2f}")
            else:
                logger.info(f"[FILL] {sig.direction} {self.cfg.order_qty}@{fill_price:.2f}")

        # 持久化状态
        state_manager.save_state(self.state)

    def _handle_stop(self, signum, frame):
        """信号处理器（Ctrl+C）。"""
        logger.info("Received stop signal")
        self._running = False
