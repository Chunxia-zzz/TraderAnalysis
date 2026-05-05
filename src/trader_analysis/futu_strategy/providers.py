"""数据源适配层。

提供 OHLCV 标准 Schema 定义、数据归一化函数和富途实时数据源。
所有外部 K 线数据必须经 normalize_ohlcv() 处理后才能进入指标计算层。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


# ── OHLCV Schema ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OHLCVSchema:
    timestamp: str = "timestamp"
    open: str = "open"
    high: str = "high"
    low: str = "low"
    close: str = "close"
    volume: str = "volume"
    symbol: str = "symbol"
    timeframe: str = "timeframe"


REQUIRED_OHLCV_COLUMNS = {
    OHLCVSchema.timestamp,
    OHLCVSchema.open,
    OHLCVSchema.high,
    OHLCVSchema.low,
    OHLCVSchema.close,
}


# ── 异常 ─────────────────────────────────────────────────────────────────────


class DataProviderError(ValueError):
    pass


# ── 归一化 ───────────────────────────────────────────────────────────────────


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def _coerce_ohlcv_types(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df[OHLCVSchema.timestamp] = pd.to_datetime(
        df[OHLCVSchema.timestamp], utc=False, errors="coerce"
    )
    if df[OHLCVSchema.timestamp].isna().any():
        bad = int(df[OHLCVSchema.timestamp].isna().sum())
        raise DataProviderError(f"Failed to parse {bad} timestamp rows.")

    for col in [OHLCVSchema.open, OHLCVSchema.high, OHLCVSchema.low, OHLCVSchema.close]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if OHLCVSchema.volume in df.columns:
        df[OHLCVSchema.volume] = pd.to_numeric(df[OHLCVSchema.volume], errors="coerce").fillna(
            0.0
        )
    else:
        df[OHLCVSchema.volume] = 0.0

    if df[[OHLCVSchema.open, OHLCVSchema.high, OHLCVSchema.low, OHLCVSchema.close]].isna().any().any():
        raise DataProviderError("OHLC columns contain NaN after numeric coercion.")

    df = df.sort_values(OHLCVSchema.timestamp).reset_index(drop=True)
    return df


def normalize_ohlcv(
    df: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
) -> pd.DataFrame:
    """将任意 K 线 DataFrame 归一化为标准 OHLCV 格式。"""
    df = _normalize_columns(df)
    missing = REQUIRED_OHLCV_COLUMNS - set(df.columns)
    if missing:
        raise DataProviderError(f"Missing required OHLCV columns: {sorted(missing)}")

    df = _coerce_ohlcv_types(df)

    if OHLCVSchema.symbol not in df.columns:
        df[OHLCVSchema.symbol] = symbol
    else:
        df[OHLCVSchema.symbol] = df[OHLCVSchema.symbol].astype(str).fillna(symbol)

    df[OHLCVSchema.timeframe] = timeframe
    return df


# ── 富途实时数据源 ───────────────────────────────────────────────────────────


@dataclass
class FutuLiveDataProvider:
    """从富途 OpenD 实时拉取 K 线数据。

    Usage::

        from futu import OpenQuoteContext
        ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
        provider = FutuLiveDataProvider()
        daily_df  = provider.get_daily(ctx, "US.AAPL")
        weekly_df = provider.get_weekly(ctx, "HK.00700")
        ctx.close()

    返回 DataFrame 经 normalize_ohlcv 标准化，列名遵循 OHLCVSchema。
    """

    def get_kline(
        self,
        quote_ctx,
        code: str,
        kl_type,
        count: int,
        *,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """通用 K 线拉取，通过 kl_type 指定周期。

        当指定 start 时自动分段拉取（每段 ~250 根），拼接后返回完整数据。

        Args:
            start: 起始日期 "YYYY-MM-DD"，指定后分段拉取 start~end 全部数据
            end: 结束日期 "YYYY-MM-DD"，默认为今天
        """
        import time as _time

        try:
            from futu import AuType  # type: ignore[import]
        except ImportError as exc:
            raise DataProviderError("futu-api 未安装，请执行: pip install futu-api") from exc

        if not start:
            # 简单模式：只拉最近 count 根
            ret, df, _ = quote_ctx.request_history_kline(
                code, ktype=kl_type, autype=AuType.QFQ, max_count=count
            )
            if ret != 0:
                raise DataProviderError(f"Futu API 拉取 {code} 失败: {df}")
            df = df.rename(columns={"time_key": OHLCVSchema.timestamp})
            return normalize_ohlcv(df, symbol=code, timeframe=timeframe)

        # 分段拉取模式：从 start 开始，每段取到的最后日期+1 天作为下段起点
        all_dfs = []
        current_start = start

        while True:
            kwargs: dict = {
                "code": code,
                "ktype": kl_type,
                "autype": AuType.QFQ,
                "start": current_start,
                "max_count": 1000,
            }
            if end:
                kwargs["end"] = end

            ret, df, _ = quote_ctx.request_history_kline(**kwargs)
            if ret != 0:
                raise DataProviderError(f"Futu API 拉取 {code} 失败: {df}")

            if df.empty:
                break

            all_dfs.append(df)

            # 如果返回不足 250 根，说明已到末尾
            if len(df) < 250:
                break

            # 下一段从最后一根的下一天开始
            last_date = str(df.iloc[-1]["time_key"])[:10]
            from datetime import datetime, timedelta
            next_start = (datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

            if end and next_start > end:
                break
            current_start = next_start
            _time.sleep(0.5)  # 避免频率限制

        if not all_dfs:
            raise DataProviderError(f"Futu API 拉取 {code} 返回空数据")

        combined = pd.concat(all_dfs, ignore_index=True).drop_duplicates(subset=["time_key"])
        combined = combined.rename(columns={"time_key": OHLCVSchema.timestamp})
        return normalize_ohlcv(combined, symbol=code, timeframe=timeframe)

    def get_daily(
        self, quote_ctx, code: str, count: int = 250, *, start: str | None = None, end: str | None = None
    ) -> pd.DataFrame:
        """拉取日线 K 线（默认 250 根，满足 MA200 计算需求）。"""
        try:
            from futu import KLType  # type: ignore[import]
        except ImportError as exc:
            raise DataProviderError("futu-api 未安装") from exc
        return self.get_kline(quote_ctx, code, KLType.K_DAY, count, timeframe="1D", start=start, end=end)

    def get_weekly(
        self, quote_ctx, code: str, count: int = 60, *, start: str | None = None, end: str | None = None
    ) -> pd.DataFrame:
        """拉取周线 K 线（默认 60 根，约 14 个月）。"""
        try:
            from futu import KLType  # type: ignore[import]
        except ImportError as exc:
            raise DataProviderError("futu-api 未安装") from exc
        return self.get_kline(quote_ctx, code, KLType.K_WEEK, count, timeframe="1W", start=start, end=end)
