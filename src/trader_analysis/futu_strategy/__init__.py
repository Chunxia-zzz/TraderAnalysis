"""富途模拟盘买入策略包。

基于多维技术指标对标的评分（0~100），70 分以上触发模拟盘买入，90 分以上触发强烈买入。

Quick start::

    python -m trader_analysis.futu_strategy
    python -m trader_analysis.futu_strategy --codes US.AAPL US.TSLA HK.00700
"""
