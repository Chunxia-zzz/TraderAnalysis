"""内容模板存储层。

将文案生成（单标的荐股）与市场复盘的模板从代码中抽离，
存入 SQLite `content_templates` 表，支持页面在线编辑。

模板使用 `{key}` 占位符，渲染时用 format_map 填充数据。
首次启动时若表为空，自动写入 DEFAULT_TEMPLATES。
"""

from __future__ import annotations

import json

from trader_analysis.futu_strategy import config

_DB_PATH = config.DB_PATH


# ── 默认模板 ──────────────────────────────────────────────────────────────────
# 占位符说明：
#   pick 模板（单标的荐股）: {ticker} {name} {score} {close} {morningstar}
#     {discount_pct} {discount_text} {tide_text} {wave_text} {rsi_text}
#     {signal} {trade_hint} {analyst_target} {upside} {date}
#   review_asset_line: {label} {ticker} {period_label} {change_desc} {close}
#     {trend} {trend_icon} {rsi_desc} {drawdown_desc}
#   review_skeleton: {period_word} {date} {macro_section} {mag7_section} {picks_section}

DEFAULT_TEMPLATES: dict[str, dict] = {
    # ── 单标的荐股文案 ────────────────────────────────────────────────
    "pick_xiaohongshu": {
        "title": "量化系统今天只选出这1只，折价{discount_text}",
        "body": (
            "跑了 196 只股票，我的系统今天只留下了 1 只 👇\n\n"
            "{ticker} · {name}\n"
            "评分 {score}/100，全场最高\n\n"
            "💰 晨星公允价值 ${morningstar}\n"
            "📉 现价才 ${close}\n"
            "折价 {discount_text}，市场给打了骨折\n\n"
            "📊 道氏三层：\n"
            "潮汐（周线）{tide_text}\n"
            "波浪（日线）{wave_text}\n"
            "涟漪 {rsi_text}\n\n"
            "系统策略：{signal}\n"
            "{trade_hint}\n\n"
            "⚠️ 折价大 ≠ 必涨，市场可能看到了我没看到的利空\n\n"
            "系统输出，不构成投资建议，理性参考"
        ),
        "hashtags": ["量化交易", "价值投资", "{ticker}", "道氏理论", "股票分析"],
    },
    "pick_zhihu": {
        "title": "196 只股票，我的量化系统为什么只留下 {ticker}？",
        "body": (
            "先说结论：{ticker}（{name}）是我这套量化系统在 {date} 唯一选出的标的。\n\n"
            "## 筛选逻辑（巴菲特三原则）\n"
            "好公司：晨星公允价值 ${morningstar}，现价 ${close}，折价 {discount_text}\n"
            "好位置：{tide_text}，{wave_text}\n"
            "好价格：6 因子评分 {score}/100，全场最高\n\n"
            "## 三个值得注意的数据\n"
            "1. 折价 {discount_text} —— 晨星 DCF 给 ${morningstar}，市场只给 ${close}\n"
            "2. {rsi_text}\n"
            "3. 系统策略信号：{signal}\n\n"
            "## 但我必须泼一盆冷水\n"
            "折价 {discount_text} 不是「稳赚」，它更可能是市场对利空的定价。\n"
            "分歧越大，越要问一句：市场知道什么是我不知道的？\n\n"
            "（量化系统输出，案例复盘，不构成任何投资建议）"
        ),
        "hashtags": [],
    },
    "pick_gongzhonghao": {
        "title": "196 只股票，我的系统只留下了这 1 只",
        "body": (
            "今天是 {date}，我照例跑了一遍量化评分系统。\n\n"
            "196 只股票，最终只有 1 只通过了全部筛选。\n\n"
            "它就是——{ticker}（{name}）。\n\n"
            "01 / 为什么是它\n"
            "三个条件同时满足：\n"
            "好公司：晨星公允价值 ${morningstar}，现价 ${close}，折价 {discount_text}\n"
            "好位置：{tide_text}\n"
            "好价格：6 因子评分 {score}/100，全场最高\n\n"
            "02 / 关键数据\n"
            "折价 {discount_text}，{rsi_text}，系统策略信号「{signal}」。\n"
            "{trade_hint}\n\n"
            "03 / 风险在哪\n"
            "折价大不代表必涨。市场给出 {discount_text} 的折扣，大概率是定价了某些利空。分歧越大，越要谨慎。\n\n"
            "写在最后\n"
            "本文是个人量化系统的案例复盘，不构成投资建议。"
        ),
        "hashtags": [],
    },
    # ── 市场复盘 ──────────────────────────────────────────────────────
    "review_asset_line": {
        "body": "{label}（{ticker}）：{period_label}{change_desc}，收 {close}，{trend}排列 {trend_icon}{rsi_desc}{drawdown_desc}"
    },
    "review_skeleton": {
        "body": (
            "# 市场{period_word}复盘（{date}）\n\n"
            "## 一、大盘概览\n\n"
            "{macro_section}\n"
            "## 二、七姐妹\n\n"
            "{mag7_section}\n"
            "## 三、交易机会\n\n"
            "{picks_section}\n"
            "---\n"
            "（以上为量化系统自动生成的复盘，不构成投资建议）"
        )
    },
}


# ── 存储层 ────────────────────────────────────────────────────────────────────


class SafeDict(dict):
    """format_map 时缺失的占位符原样保留，避免 KeyError。"""

    def __missing__(self, key):
        return "{" + key + "}"


def _get_conn():
    import sqlite3
    import os

    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_templates_table() -> None:
    """建表（幂等），若表为空则写入默认模板。"""
    conn = _get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS content_templates (
            template_key TEXT PRIMARY KEY,
            title        TEXT NOT NULL DEFAULT '',
            body         TEXT NOT NULL DEFAULT '',
            hashtags     TEXT NOT NULL DEFAULT '[]',
            updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()

    # 空表时写入默认模板
    count = conn.execute("SELECT COUNT(*) as n FROM content_templates").fetchone()["n"]
    if count == 0:
        for key, tpl in DEFAULT_TEMPLATES.items():
            conn.execute(
                "INSERT INTO content_templates (template_key, title, body, hashtags) VALUES (?, ?, ?, ?)",
                (key, tpl.get("title", ""), tpl.get("body", ""), json.dumps(tpl.get("hashtags", []), ensure_ascii=False)),
            )
        conn.commit()
    conn.close()


def get_template(key: str) -> dict:
    """读取单个模板，不存在则回退到默认模板。"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM content_templates WHERE template_key = ?", (key,)).fetchone()
    conn.close()
    if row:
        return {
            "key": key,
            "title": row["title"],
            "body": row["body"],
            "hashtags": json.loads(row["hashtags"]) if row["hashtags"] else [],
            "updated_at": row["updated_at"],
        }
    default = DEFAULT_TEMPLATES.get(key, {})
    return {
        "key": key,
        "title": default.get("title", ""),
        "body": default.get("body", ""),
        "hashtags": default.get("hashtags", []),
        "updated_at": None,
    }


def list_templates() -> list[dict]:
    """列出所有模板（含默认模板中尚未入库的）。"""
    conn = _get_conn()
    rows = {r["template_key"]: r for r in conn.execute("SELECT * FROM content_templates").fetchall()}
    conn.close()

    # 合并默认模板，确保所有 key 都在
    keys = set(DEFAULT_TEMPLATES) | set(rows)
    result = []
    for key in sorted(keys):
        row = rows.get(key)
        default = DEFAULT_TEMPLATES.get(key, {})
        result.append({
            "key": key,
            "title": row["title"] if row else default.get("title", ""),
            "body": row["body"] if row else default.get("body", ""),
            "hashtags": (json.loads(row["hashtags"]) if row and row["hashtags"] else default.get("hashtags", [])),
            "is_custom": key in rows,
        })
    return result


def save_template(key: str, title: str = "", body: str = "", hashtags: list[str] | None = None) -> dict:
    """保存/更新模板。"""
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO content_templates (template_key, title, body, hashtags, updated_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT(template_key) DO UPDATE SET
            title = excluded.title,
            body = excluded.body,
            hashtags = excluded.hashtags,
            updated_at = datetime('now')
        """,
        (key, title, body, json.dumps(hashtags or [], ensure_ascii=False)),
    )
    conn.commit()
    conn.close()
    return get_template(key)


def delete_template(key: str) -> dict:
    """删除自定义模板，回退到默认模板。"""
    conn = _get_conn()
    conn.execute("DELETE FROM content_templates WHERE template_key = ?", (key,))
    conn.commit()
    conn.close()
    return get_template(key)


def render(template_text: str, data: dict) -> str:
    """渲染模板，占位符 {key} 用 data[key] 填充，缺失占位符原样保留。"""
    return template_text.format_map(SafeDict(data))
