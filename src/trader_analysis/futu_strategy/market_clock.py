"""美股/港股交易时钟：判断一根 K 线是否已经「收盘定稿」。

## 为什么需要这个模块

`daily_update._update_ktype()` 的增量过滤是 **`date > last_date`（严格大于）**，
所以**一旦把某根 K 线写进库，就永远不会被覆盖**。

北京时间 21:30 之后（= 美东盘中）跑 `update`，Futu 会把**当天进行中的那根 K 线**
一并返回。这根半截 K 线一旦落库：

- 评分 / 市场温度 / 信号全部建立在未收盘数据上；
- 之后**再跑 `update` 也修不回来**（严格大于 → 「无新增数据」），
  必须手工 `DELETE` 掉那根再重拉（2026-10-17 踩过：10/16 的 40.6 分其实是盘中值，
  收盘后重算是 36.8 分，强买榜从 22 只变成 33 只）。

本模块提供 `is_bar_closed()` / `filter_closed_bars()`，让写入路径**只落已定稿的 K 线**，
盘中跑就自动停在「上一个完整交易日」，不需要任何人记住这条规则。

## 判定规则（各市场本地时间）

| ktype | `date` 语义 | 视为已收盘的条件 |
|---|---|---|
| `1d` | 交易日 | 本地时间已过该日 **16:00** |
| `1w` | 该周**周一** | 本地时间已过该周**周五 16:00** |
| `4h` | K 线**结束**时刻 | 本地时间已过该时刻 |

## 已验证的事实（2026-10-17 联网实测，别改回去）

- **4H 的 `date` 是 K 线结束时刻，不是开始时刻**：
  美股 SPY 每天两根 = `13:30` + `16:00`（09:30–13:30 → 13:30；13:30–16:00 → 16:00），
  港股 00700 = `12:00` + `16:00`（09:30–12:00 → 12:00；13:00–16:00 → 16:00）。
  500 根 SPY 4H 的标签分布 = `13:30`×249 / `16:00`×249 / **`13:00`×2**，
  那 2 根分别是 **2025-11-28（感恩节次日）** 与 **2025-12-24（平安夜）** 的半日市，当天只有 1 根。
  若哪天发现 label 实际是开始时刻，最坏结果只是**晚 4 小时入库**，不会写入半截数据，安全。
- **美股与港股收盘都是本地 16:00**，所以 1d/1w 可以共用同一个收盘时刻常量。
- **半日市**：4H 因标签本身就是 `13:00`，所以准时入库；但 **1d 会等到本地 16:00 才入库**（晚 3 小时）。
  方向安全——只会晚、不会写半截，因此不为它单独维护节假日表。
- **时区分支必须生效**：同一时刻（美东周五 12:19 = 香港周六 00:19）美股在盘中要拦、
  港股已收盘要放行。联网验证里专门测了这一条。
- 时区用 `zoneinfo`（本机已装 tzdata 2026.2）；`HK.` 前缀走香港时区，其余按美股处理。

## 关闭方式

设环境变量 `TA_ALLOW_PARTIAL_BAR=1`（或 `config.ALLOW_PARTIAL_BAR=True`）即恢复旧行为，
把盘中那根也写进去。**非调试/非补偿场景不要开。**
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

__all__ = [
    "CLOSE_HOUR",
    "allow_partial_bar",
    "filter_closed_bars",
    "is_bar_closed",
    "market_tz",
    "now_in_market",
]

#: 各市场收盘时刻（本地时间整点）。美股与港股都是 16:00。
CLOSE_HOUR: int = 16

_MARKET_TZ: dict[str, str] = {
    "US": "America/New_York",
    "HK": "Asia/Hong_Kong",
}
_DEFAULT_MARKET: str = "US"

_TRUE_STRINGS = {"1", "true", "yes", "on", "y"}


def allow_partial_bar() -> bool:
    """是否允许写入未收盘的 K 线（默认 False）。

    优先级：环境变量 `TA_ALLOW_PARTIAL_BAR` > `config.ALLOW_PARTIAL_BAR`。
    """
    env = os.environ.get("TA_ALLOW_PARTIAL_BAR")
    if env is not None:
        return env.strip().lower() in _TRUE_STRINGS
    try:
        from trader_analysis.futu_strategy import config

        return bool(getattr(config, "ALLOW_PARTIAL_BAR", False))
    except Exception:  # pragma: no cover - 配置导入失败时按安全默认
        return False


def market_tz(code: str) -> ZoneInfo:
    """按代码前缀返回所属市场时区。`HK.00700` → 香港，其余（含无前缀）→ 纽约。"""
    prefix = (code or "").split(".")[0].upper()
    return ZoneInfo(_MARKET_TZ.get(prefix, _MARKET_TZ[_DEFAULT_MARKET]))


def now_in_market(code: str, now: datetime | None = None) -> datetime:
    """取该市场的当前本地时间。`now` 传入时必须带时区（用于测试注入）。"""
    tz = market_tz(code)
    if now is None:
        return datetime.now(timezone.utc).astimezone(tz)
    if now.tzinfo is None:
        raise ValueError("now 必须带时区信息")
    return now.astimezone(tz)


def _to_date(value: object) -> date | None:
    """把 'YYYY-MM-DD'（或带时间的字符串）转成 date，失败返回 None。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _to_local_datetime(value: object) -> datetime | None:
    """把 'YYYY-MM-DD HH:MM:SS' 解析成**无时区**的本地市场时间，失败返回 None。"""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def is_bar_closed(
    ktype: str,
    bar_value: object,
    code: str = "",
    now: datetime | None = None,
) -> bool:
    """判断一根 K 线是否已收盘定稿。

    Args:
        ktype: `1d` / `1w` / `4h`（其他类型一律视为已收盘，不受本约束）。
        bar_value: 该行的 `date`，格式随 ktype 而定（见模块文档表格）。
        code: 标的代码，用于选时区（`HK.` 前缀走香港）。
        now: 注入的当前时间（带时区），默认取真实时间。仅供测试。

    Returns:
        True = 已收盘、可以入库；False = 仍在进行中、应丢弃。

    解析失败时**放行**（返回 True）：宁可多写一根历史 K 线，也不要因为格式意外
    把整批数据静默丢掉。
    """
    if ktype not in ("1d", "1w", "4h"):
        return True

    current = now_in_market(code, now)
    tz = current.tzinfo

    if ktype == "1d":
        d = _to_date(bar_value)
        if d is None:
            return True
        if current.date() > d:
            return True
        return current.date() == d and current.time() >= time(CLOSE_HOUR)

    if ktype == "1w":
        d = _to_date(bar_value)
        if d is None:
            return True
        # 周线 date 记的是该周**周一**（实测 52 周全为周一）。
        # 先归一化到周一再 +4 天，任何 weekday 都能算出正确的周五，
        # 不依赖「传入的必须是周一」这个隐含前提。
        monday = d - timedelta(days=d.weekday())
        close_at = datetime.combine(monday + timedelta(days=4), time(CLOSE_HOUR), tzinfo=tz)
        return current >= close_at

    # 4h：date 是 K 线结束时刻（本地市场时间）
    ts = _to_local_datetime(bar_value)
    if ts is None:
        return True
    return current >= ts.replace(tzinfo=tz)


def filter_closed_bars(
    df,
    ktype: str,
    code: str = "",
    now: datetime | None = None,
    column: str = "date",
):
    """过滤掉 `df` 中尚未收盘的 K 线，返回新 DataFrame（不改原对象）。

    `TA_ALLOW_PARTIAL_BAR=1` 时原样返回。
    """
    if allow_partial_bar():
        return df
    if df is None or getattr(df, "empty", True) or column not in df.columns:
        return df

    mask = df[column].map(lambda v: is_bar_closed(ktype, v, code, now))
    return df[mask.fillna(True).astype(bool)]


def dropped_bar_summary(df_before, df_after, ktype: str) -> str:
    """生成一句「丢弃了几根、最后一根是什么」的日志尾巴（供调用方复用）。"""
    try:
        dropped = len(df_before) - len(df_after)
    except TypeError:  # pragma: no cover
        return ""
    if dropped <= 0:
        return ""
    try:
        last = str(df_before.iloc[-1].get("date", ""))
    except Exception:  # pragma: no cover
        last = ""
    return f"跳过 {dropped} 根未收盘 {ktype}（最后一根 {last}）"
