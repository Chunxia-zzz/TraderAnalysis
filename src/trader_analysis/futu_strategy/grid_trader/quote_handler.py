"""行情推送回调处理。"""

from __future__ import annotations

import logging

logger = logging.getLogger("grid_trader")


def create_quote_handler(engine):
    """创建行情回调 handler，绑定到 engine。

    返回 handler 类（需要在运行时 import futu）。
    """
    from futu import RET_OK, StockQuoteHandlerBase

    class GridQuoteHandler(StockQuoteHandlerBase):
        """实时报价回调，转发价格到引擎。"""

        def on_recv_rsp(self, rsp_pb):
            ret, data = super().on_recv_rsp(rsp_pb)
            if ret != RET_OK:
                return
            for _, row in data.iterrows():
                price = row.get("last_price")
                code = row.get("code")
                if price and code:
                    engine.on_price_update(code, float(price))

    return GridQuoteHandler()
