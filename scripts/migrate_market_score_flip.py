"""一次性迁移：市场温度分数口径镜像反转（2026-10-19）。

新口径：分数越高 = 越恐慌 = 越值得加仓（与个股评分 total_score 同向）。

原理：所有子项对原始指标均为线性映射，故 new = 100 - old 与全量滑窗重算严格等价
（回溯窗口一致、加权线性保持镜像）。因此：
  - market_score 中 *_score 列全部做 100 - x
  - market_score_detail.detail_json 中键名以 _score 结尾的数值做 100 - x
  - target_position_pct / extreme_triggered / leverage_tool 数学上逐位不变，不迁移
  - 原始指标列（RSI/价格/偏离度等）不迁移

用法：C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe scripts/migrate_market_score_flip.py
幂等性：非幂等，只能执行一次（重复执行会把分数翻回去）。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "indicators.db"

SCORE_COLS = [
    "composite_score",
    "daily_tech_score",
    "weekly_tech_score",
    "price_score",
    "vol_score",
    "volume_score",
    "safe_haven_score",
]


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # ── 1. market_score 数值列 ──
    before = cur.execute(
        "SELECT date, composite_score, daily_tech_score FROM market_score "
        "ORDER BY date DESC LIMIT 3"
    ).fetchall()
    print("迁移前样例:", before)

    for col in SCORE_COLS:
        n = cur.execute(
            f"UPDATE market_score SET {col} = 100 - {col} WHERE {col} IS NOT NULL"
        ).rowcount
        print(f"market_score.{col}: {n} 行已反转")

    # ── 2. market_score_detail.detail_json ──
    rows = cur.execute("SELECT date, detail_json FROM market_score_detail").fetchall()
    flipped = 0
    for date, dj in rows:
        d = json.loads(dj)
        changed = False
        for k, v in d.items():
            if k.endswith("_score") and isinstance(v, (int, float)):
                d[k] = round(100 - v, 1)
                changed = True
        if changed:
            cur.execute(
                "UPDATE market_score_detail SET detail_json = ? WHERE date = ?",
                (json.dumps(d, ensure_ascii=False), date),
            )
            flipped += 1
    print(f"market_score_detail: {flipped}/{len(rows)} 行已反转")

    conn.commit()

    after = cur.execute(
        "SELECT date, composite_score, daily_tech_score FROM market_score "
        "ORDER BY date DESC LIMIT 3"
    ).fetchall()
    print("迁移后样例:", after)

    # ── 3. 校验：composite 应落在 [0,100]，且每个 _score 键值合法 ──
    bad = cur.execute(
        "SELECT COUNT(*) FROM market_score WHERE composite_score < 0 OR composite_score > 100"
    ).fetchone()[0]
    print(f"越界校验: {bad} 行越界（应为 0）")
    conn.close()
    print("迁移完成")


if __name__ == "__main__":
    main()
