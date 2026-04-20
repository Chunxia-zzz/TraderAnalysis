"""富途模拟盘买入策略包（v2.0 三层架构）。

基于多维技术指标对标的评分（0~100），70 分以上触发模拟盘买入，90 分以上触发强烈买入。

架构：
  Part A — 后端核心层：数据获取、指标计算、评分、交易执行
  Part B — 持久化存储层：SQLite 存储 K 线 + 指标 + 评分结果
  Part C — API 服务层：FastAPI 只读接口，供前端消费

Quick start::

    # 首次初始化历史数据
    python -m trader_analysis.futu_strategy.init_history --codes US.AAPL HK.00700

    # 日常运行（增量更新 + 评分 + 交易）
    python -m trader_analysis.futu_strategy
    python -m trader_analysis.futu_strategy --codes US.AAPL US.TSLA HK.00700

    # 启动 API 服务（独立于 Futu OpenD）
    uvicorn trader_analysis.futu_strategy.api_server:app --port 8000
"""
